// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/access/Ownable2Step.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";

/**
 * @title SIGProfitDistributor
 * @notice Pull-payment profit distributor for SIG / Al Shumookh project.
 *         Receives native coin (BNB/ETH) and ERC20/BEP20 tokens, then lets
 *         registered payees claim their pro-rata share at any time.
 *
 * @dev Key design decisions:
 *  - Pull payment: no mass-payout loops; each payee calls claim themselves.
 *  - Basis-points (BPS): 10 000 = 100 %.  Sum of all payee shares must be 10 000.
 *  - Two-phase lifecycle: (1) setup -> (2) frozen shares -> (3) optionally closed deposits.
 *  - Closing deposits does NOT block claims - old balances remain claimable forever.
 *  - Rescue functions only touch untracked funds (sent by mistake, not via deposit).
 *  - Does NOT interact with, pause, burn, or modify any external token contract.
 */
contract SIGProfitDistributor is Ownable2Step, ReentrancyGuard {
    using SafeERC20 for IERC20;

    // -------------------------------------------------------------------------
    // Custom errors
    // -------------------------------------------------------------------------
    error InvalidInput();
    error InvalidPayee();
    error SharesAlreadyFrozen();
    error SharesNotFrozen();
    error DepositsAreClosed();
    error NothingToClaim();
    error NothingToRescue();
    error NativeTransferFailed();

    // -------------------------------------------------------------------------
    // Events
    // -------------------------------------------------------------------------
    event PayeesSet(address[] payees, uint256[] sharesBps);
    event SharesFrozen();
    event DepositsClosed();
    event NativeDeposited(address indexed from, uint256 amount);
    event TokenDeposited(address indexed from, address indexed token, uint256 amountReceived);
    event NativeClaimed(address indexed payee, uint256 amount);
    event TokenClaimed(address indexed payee, address indexed token, uint256 amount);
    event UntrackedNativeRescued(address indexed to, uint256 amount);
    event UntrackedTokenRescued(address indexed token, address indexed to, uint256 amount);

    // -------------------------------------------------------------------------
    // Constants
    // -------------------------------------------------------------------------
    uint256 public constant BPS_DENOMINATOR = 10_000;
    uint256 public constant MAX_PAYEES = 100;

    /// @dev address(0) is used as the key for native coin (BNB / ETH)
    address private constant NATIVE = address(0);

    // -------------------------------------------------------------------------
    // State
    // -------------------------------------------------------------------------
    bool public sharesFrozen;
    bool public depositsClosed;

    address[] private _payees;
    mapping(address => uint256) public shareBps; // payee => basis points

    /// @dev Total amount of each asset ever deposited (tracked).
    ///      Key: address(0) = native, token address = ERC20.
    mapping(address => uint256) private _totalReceived;

    /// @dev Amount already claimed per payee per asset.
    mapping(address => mapping(address => uint256)) private _claimed; // asset => payee => amount

    // -------------------------------------------------------------------------
    // Constructor
    // -------------------------------------------------------------------------
    /**
     * @param initialOwner The address that will own this contract.
     *                     Must not be address(0).
     */
    constructor(address initialOwner) Ownable(initialOwner) {
        if (initialOwner == address(0)) revert InvalidInput();
    }

    // -------------------------------------------------------------------------
    // Setup - Payee Registration
    // -------------------------------------------------------------------------

    /**
     * @notice Register all payees and their BPS shares in one call.
     *         Can be called multiple times before shares are frozen (to replace).
     * @param accounts  Array of payee addresses.
     * @param bpsValues Array of basis-point shares (must sum to 10 000).
     */
    function setPayees(
        address[] calldata accounts,
        uint256[] calldata bpsValues
    ) external onlyOwner {
        if (sharesFrozen) revert SharesAlreadyFrozen();
        if (accounts.length == 0 || accounts.length != bpsValues.length) revert InvalidInput();
        if (accounts.length > MAX_PAYEES) revert InvalidInput();

        // Clear previous payees
        for (uint256 i = 0; i < _payees.length; i++) {
            delete shareBps[_payees[i]];
        }
        delete _payees;

        uint256 total = 0;
        for (uint256 i = 0; i < accounts.length; i++) {
            address account = accounts[i];
            uint256 bps = bpsValues[i];

            if (account == address(0)) revert InvalidPayee();
            if (bps == 0) revert InvalidInput();
            if (shareBps[account] != 0) revert InvalidPayee(); // duplicate

            shareBps[account] = bps;
            _payees.push(account);
            total += bps;
        }

        if (total != BPS_DENOMINATOR) revert InvalidInput();

        emit PayeesSet(accounts, bpsValues);
    }

    // -------------------------------------------------------------------------
    // Setup - Freeze Shares
    // -------------------------------------------------------------------------

    /**
     * @notice Permanently lock payee list and shares.
     *         Must be called before any deposits are accepted.
     *         Cannot be undone.
     */
    function freezeShares() external onlyOwner {
        if (sharesFrozen) revert SharesAlreadyFrozen();
        if (_payees.length == 0) revert InvalidInput();
        sharesFrozen = true;
        emit SharesFrozen();
    }

    // -------------------------------------------------------------------------
    // Deposits - Native Coin
    // -------------------------------------------------------------------------

    /// @notice Accept native coin deposits via plain ETH/BNB send.
    receive() external payable {
        _depositNative();
    }

    /// @notice Accept native coin deposit (explicit call).
    function depositNative() external payable {
        _depositNative();
    }

    function _depositNative() internal {
        if (!sharesFrozen) revert SharesNotFrozen();
        if (depositsClosed) revert DepositsAreClosed();
        if (msg.value == 0) revert InvalidInput();

        _totalReceived[NATIVE] += msg.value;
        emit NativeDeposited(msg.sender, msg.value);
    }

    // -------------------------------------------------------------------------
    // Deposits - ERC20 / BEP20
    // -------------------------------------------------------------------------

    /**
     * @notice Deposit ERC20/BEP20 tokens.
     *         Caller must have approved this contract for `amount` of `token`.
     *         Uses before/after balance accounting to handle fee-on-transfer tokens.
     * @param token  Token contract address (must not be address(0)).
     * @param amount Amount to pull from caller.
     */
    function depositToken(address token, uint256 amount) external nonReentrant {
        if (!sharesFrozen) revert SharesNotFrozen();
        if (depositsClosed) revert DepositsAreClosed();
        if (token == address(0)) revert InvalidInput();
        if (amount == 0) revert InvalidInput();

        uint256 before = IERC20(token).balanceOf(address(this));
        IERC20(token).safeTransferFrom(msg.sender, address(this), amount);
        uint256 received = IERC20(token).balanceOf(address(this)) - before;

        _totalReceived[token] += received;
        emit TokenDeposited(msg.sender, token, received);
    }

    // -------------------------------------------------------------------------
    // Claims - Native Coin
    // -------------------------------------------------------------------------

    /// @notice Claim caller's accumulated native coin share.
    function claimNative() external nonReentrant {
        _claimNative(msg.sender);
    }

    /**
     * @notice Claim native coin on behalf of a payee.
     *         Funds are always sent to the payee, never to the caller.
     * @param payee The registered payee address.
     */
    function claimNativeFor(address payee) external nonReentrant {
        _claimNative(payee);
    }

    function _claimNative(address payee) internal {
        uint256 amount = _claimableNow(NATIVE, payee);
        if (amount == 0) revert NothingToClaim();

        _claimed[NATIVE][payee] += amount;

        (bool ok, ) = payable(payee).call{value: amount}("");
        if (!ok) revert NativeTransferFailed();

        emit NativeClaimed(payee, amount);
    }

    // -------------------------------------------------------------------------
    // Claims - ERC20 / BEP20
    // -------------------------------------------------------------------------

    /// @notice Claim caller's accumulated share of an ERC20 token.
    function claimToken(address token) external nonReentrant {
        _claimToken(token, msg.sender);
    }

    /**
     * @notice Claim token on behalf of a payee.
     *         Funds are always sent to the payee, never to the caller.
     * @param token Token contract address.
     * @param payee The registered payee address.
     */
    function claimTokenFor(address token, address payee) external nonReentrant {
        _claimToken(token, payee);
    }

    function _claimToken(address token, address payee) internal {
        if (token == address(0)) revert InvalidInput();
        uint256 amount = _claimableNow(token, payee);
        if (amount == 0) revert NothingToClaim();

        _claimed[token][payee] += amount;
        IERC20(token).safeTransfer(payee, amount);

        emit TokenClaimed(payee, token, amount);
    }

    // -------------------------------------------------------------------------
    // Close Deposits
    // -------------------------------------------------------------------------

    /**
     * @notice Permanently stop accepting new deposits.
     *         Claims remain open forever - payees can still claim old balances.
     *         Use when an investor agreement ends: close this distributor, then
     *         deploy a new one for future profits.
     */
    function closeDeposits() external onlyOwner {
        if (!sharesFrozen) revert SharesNotFrozen();
        if (depositsClosed) revert DepositsAreClosed();
        depositsClosed = true;
        emit DepositsClosed();
    }

    // -------------------------------------------------------------------------
    // Rescue - Untracked Funds Only
    // -------------------------------------------------------------------------

    /**
     * @notice Rescue native coin sent to the contract by mistake (not via depositNative).
     *         Cannot touch tracked investor funds.
     */
    function rescueUntrackedNative(
        address payable to,
        uint256 amount
    ) external onlyOwner nonReentrant {
        if (to == address(0)) revert InvalidInput();
        uint256 untracked = _untrackedBalance(NATIVE);
        if (amount == 0 || amount > untracked) revert NothingToRescue();

        (bool ok, ) = to.call{value: amount}("");
        if (!ok) revert NativeTransferFailed();

        emit UntrackedNativeRescued(to, amount);
    }

    /**
     * @notice Rescue ERC20 tokens sent by mistake (not via depositToken).
     *         Cannot touch tracked investor funds.
     */
    function rescueUntrackedToken(
        address token,
        address to,
        uint256 amount
    ) external onlyOwner nonReentrant {
        if (token == address(0) || to == address(0)) revert InvalidInput();
        uint256 untracked = _untrackedBalance(token);
        if (amount == 0 || amount > untracked) revert NothingToRescue();

        IERC20(token).safeTransfer(to, amount);

        emit UntrackedTokenRescued(token, to, amount);
    }

    // -------------------------------------------------------------------------
    // View Functions
    // -------------------------------------------------------------------------

    /// @notice Returns the full list of registered payee addresses.
    function payees() external view returns (address[] memory) {
        return _payees;
    }

    /// @notice Returns the payee at a given index.
    function payeeAt(uint256 index) external view returns (address) {
        if (index >= _payees.length) revert InvalidInput();
        return _payees[index];
    }

    /// @notice Returns the number of registered payees.
    function payeeCount() external view returns (uint256) {
        return _payees.length;
    }

    /**
     * @notice Amount a payee can claim right now for a given asset.
     * @param asset  address(0) for native coin; token address for ERC20.
     * @param payee  The payee address.
     */
    function claimable(address asset, address payee) external view returns (uint256) {
        return _claimableNow(asset, payee);
    }

    /// @notice Total amount of an asset ever deposited via deposit functions.
    function totalReceived(address asset) external view returns (uint256) {
        return _totalReceived[asset];
    }

    /// @notice Total amount of an asset claimed by all payees so far.
    function totalClaimed(address asset) external view returns (uint256) {
        uint256 sum = 0;
        for (uint256 i = 0; i < _payees.length; i++) {
            sum += _claimed[asset][_payees[i]];
        }
        return sum;
    }

    /// @notice Amount of an asset already claimed by a specific payee.
    function claimedBy(address asset, address payee) external view returns (uint256) {
        return _claimed[asset][payee];
    }

    /**
     * @notice Tracked balance = total ever received minus total ever claimed.
     *         Represents funds still owed to payees.
     */
    function trackedBalance(address asset) external view returns (uint256) {
        return _trackedBalance(asset);
    }

    /**
     * @notice Actual current balance of the asset held by this contract.
     */
    function currentBalance(address asset) external view returns (uint256) {
        return _currentBalance(asset);
    }

    /**
     * @notice Funds held by the contract that are NOT tracked (sent by mistake).
     *         These are safe to rescue; they do not belong to any payee.
     */
    function untrackedBalance(address asset) external view returns (uint256) {
        return _untrackedBalance(asset);
    }

    // -------------------------------------------------------------------------
    // Internal Helpers
    // -------------------------------------------------------------------------

    function _claimableNow(address asset, address payee) internal view returns (uint256) {
        uint256 bps = shareBps[payee];
        if (bps == 0) return 0;
        uint256 total = _totalReceived[asset];
        uint256 entitled = (total * bps) / BPS_DENOMINATOR;
        uint256 alreadyClaimed = _claimed[asset][payee];
        if (entitled <= alreadyClaimed) return 0;
        return entitled - alreadyClaimed;
    }

    function _currentBalance(address asset) internal view returns (uint256) {
        if (asset == NATIVE) {
            return address(this).balance;
        }
        return IERC20(asset).balanceOf(address(this));
    }

    function _trackedBalance(address asset) internal view returns (uint256) {
        uint256 totalEverClaimed = 0;
        for (uint256 i = 0; i < _payees.length; i++) {
            totalEverClaimed += _claimed[asset][_payees[i]];
        }
        uint256 rec = _totalReceived[asset];
        if (rec <= totalEverClaimed) return 0;
        return rec - totalEverClaimed;
    }

    function _untrackedBalance(address asset) internal view returns (uint256) {
        uint256 current = _currentBalance(asset);
        uint256 tracked = _trackedBalance(asset);
        if (current <= tracked) return 0;
        return current - tracked;
    }
}
