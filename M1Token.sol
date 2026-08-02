// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/token/ERC20/extensions/ERC20Burnable.sol";
import "@openzeppelin/contracts/token/ERC20/extensions/ERC20Pausable.sol";
import "@openzeppelin/contracts/access/AccessControl.sol";

/**
 * @title M1Token — Al Shumookh M1 Fund Token
 * @notice Reserve-backed token representing the M1 Fund.
 *         Each M1 token is backed by USD-equivalent EUR reserves.
 *         Reserve is tracked on-chain for full transparency.
 *
 * Roles:
 *   DEFAULT_ADMIN_ROLE  — manage roles and max supply
 *   MINTER_ROLE         — mint tokens (used by ASIG system on EUR receipt)
 *   PAUSER_ROLE         — pause/unpause transfers in emergencies
 *   RESERVE_MANAGER_ROLE— update the on-chain reserve value
 */
contract M1Token is ERC20, ERC20Burnable, ERC20Pausable, AccessControl {

    // ─── Roles ────────────────────────────────────────────────────────────────
    bytes32 public constant MINTER_ROLE          = keccak256("MINTER_ROLE");
    bytes32 public constant PAUSER_ROLE          = keccak256("PAUSER_ROLE");
    bytes32 public constant RESERVE_MANAGER_ROLE = keccak256("RESERVE_MANAGER_ROLE");

    // ─── Supply cap ───────────────────────────────────────────────────────────
    uint256 public maxSupply;

    // ─── Reserve tracking (stored in USD cents for precision) ─────────────────
    // Example: 26_637_781_50 = $26,637,781.50 USD
    uint256 public totalReserveUSDCents;   // on-chain EUR→USD backing
    uint256 public lastReserveUpdateAt;    // Unix timestamp of last update

    // ─── Events ───────────────────────────────────────────────────────────────
    event MaxSupplyUpdated(uint256 oldMaxSupply, uint256 newMaxSupply);
    event ReserveUpdated(uint256 oldReserveUSDCents, uint256 newReserveUSDCents, string source);
    event MintedWithReserve(address indexed to, uint256 amount, uint256 reserveAddedUSDCents);

    // ─── Constructor ──────────────────────────────────────────────────────────
    constructor(address admin, uint256 initialMaxSupply)
        ERC20("Al Shumookh M1 Fund Token", "M1")
    {
        require(admin != address(0), "Invalid admin");
        require(initialMaxSupply > 0, "Invalid max supply");

        maxSupply = initialMaxSupply * 10 ** decimals();

        _grantRole(DEFAULT_ADMIN_ROLE,  admin);
        _grantRole(MINTER_ROLE,         admin);
        _grantRole(PAUSER_ROLE,         admin);
        _grantRole(RESERVE_MANAGER_ROLE,admin);
    }

    // ─── Mint ─────────────────────────────────────────────────────────────────

    /**
     * @notice Standard mint — used for internal treasury minting.
     */
    function mint(address to, uint256 amount) external onlyRole(MINTER_ROLE) {
        require(totalSupply() + amount <= maxSupply, "Max supply exceeded");
        _mint(to, amount);
    }

    /**
     * @notice Mint + record EUR reserve in one transaction.
     * @param to                  Recipient address (treasury or client wallet).
     * @param amount              Token amount (with 18 decimals).
     * @param reserveAddedUSDCents USD value of the EUR deposit in cents.
     *                            Example: EUR 23,085,000 @ 1.1537 = $26,637,781.50
     *                            → pass 2663778150
     * @param source              Human-readable source label (e.g. "VALUES_AND_FRIENDS_M1_2026").
     */
    function mintWithReserve(
        address to,
        uint256 amount,
        uint256 reserveAddedUSDCents,
        string calldata source
    ) external onlyRole(MINTER_ROLE) {
        require(totalSupply() + amount <= maxSupply, "Max supply exceeded");
        require(reserveAddedUSDCents > 0, "Reserve amount must be > 0");

        _mint(to, amount);

        uint256 oldReserve = totalReserveUSDCents;
        totalReserveUSDCents   += reserveAddedUSDCents;
        lastReserveUpdateAt     = block.timestamp;

        emit MintedWithReserve(to, amount, reserveAddedUSDCents);
        emit ReserveUpdated(oldReserve, totalReserveUSDCents, source);
    }

    // ─── Reserve management ───────────────────────────────────────────────────

    /**
     * @notice Update the on-chain reserve without minting.
     *         Used when adding fiat backing without issuing new tokens.
     */
    function updateReserve(
        uint256 newTotalReserveUSDCents,
        string calldata source
    ) external onlyRole(RESERVE_MANAGER_ROLE) {
        uint256 old = totalReserveUSDCents;
        totalReserveUSDCents = newTotalReserveUSDCents;
        lastReserveUpdateAt  = block.timestamp;
        emit ReserveUpdated(old, newTotalReserveUSDCents, source);
    }

    // ─── View helpers ─────────────────────────────────────────────────────────

    /**
     * @notice Returns the USD backing per M1 token (in cents).
     *         Example: reserve=$26,637,781 supply=26,637,781 → 100 cents = $1.00 per M1
     */
    function reservePerTokenCents() external view returns (uint256) {
        if (totalSupply() == 0) return 0;
        // reserveUSDCents * 10^18 / totalSupply (normalised)
        return (totalReserveUSDCents * 10 ** decimals()) / totalSupply();
    }

    /**
     * @notice Returns the reserve ratio as a percentage (×100).
     *         100_00 = 100.00% fully backed, >100_00 = over-collateralised.
     */
    function backingRatioBps() external view returns (uint256) {
        if (totalSupply() == 0) return 0;
        // totalReserveUSDCents * 10^18 / (totalSupply * 100 cents per dollar / 100)
        uint256 supplyInCents = totalSupply() / 10 ** (decimals() - 2);
        if (supplyInCents == 0) return 0;
        return (totalReserveUSDCents * 10_000) / supplyInCents;
    }

    // ─── Supply cap management ────────────────────────────────────────────────

    function setMaxSupply(uint256 newMaxSupply) external onlyRole(DEFAULT_ADMIN_ROLE) {
        uint256 newMax = newMaxSupply * 10 ** decimals();
        require(newMax >= totalSupply(), "Below current supply");
        uint256 old = maxSupply;
        maxSupply = newMax;
        emit MaxSupplyUpdated(old, newMax);
    }

    // ─── Pause ────────────────────────────────────────────────────────────────

    function pause()   external onlyRole(PAUSER_ROLE) { _pause(); }
    function unpause() external onlyRole(PAUSER_ROLE) { _unpause(); }

    // ─── Internal override ────────────────────────────────────────────────────

    function _update(address from, address to, uint256 value)
        internal
        override(ERC20, ERC20Pausable)
    {
        super._update(from, to, value);
    }
}
