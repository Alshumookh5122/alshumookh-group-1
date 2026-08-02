// SPDX-License-Identifier: MIT
// File: @openzeppelin/contracts/token/ERC20/IERC20.sol
pragma solidity ^0.8.20;

interface IERC20 {
    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);
    function totalSupply() external view returns (uint256);
    function balanceOf(address account) external view returns (uint256);
    function transfer(address to, uint256 value) external returns (bool);
    function allowance(address owner, address spender) external view returns (uint256);
    function approve(address spender, uint256 value) external returns (bool);
    function transferFrom(address from, address to, uint256 value) external returns (bool);
}

interface IERC20Metadata is IERC20 {
    function name() external view returns (string memory);
    function symbol() external view returns (string memory);
    function decimals() external view returns (uint8);
}

abstract contract Context {
    function _msgSender() internal view virtual returns (address) { return msg.sender; }
    function _msgData() internal view virtual returns (bytes calldata) { return msg.data; }
    function _contextSuffixLength() internal view virtual returns (uint256) { return 0; }
}

interface IERC20Errors {
    error ERC20InsufficientBalance(address sender, uint256 balance, uint256 needed);
    error ERC20InvalidSender(address sender);
    error ERC20InvalidReceiver(address receiver);
    error ERC20InsufficientAllowance(address spender, uint256 allowance, uint256 needed);
    error ERC20InvalidApprover(address approver);
    error ERC20InvalidSpender(address spender);
}

interface IERC721Errors {
    error ERC721InvalidOwner(address owner);
    error ERC721NonexistentToken(uint256 tokenId);
    error ERC721IncorrectOwner(address sender, uint256 tokenId, address owner);
    error ERC721InvalidSender(address sender);
    error ERC721InvalidReceiver(address receiver);
    error ERC721InsufficientApproval(address operator, uint256 tokenId);
    error ERC721InvalidApprover(address approver);
    error ERC721InvalidOperator(address operator);
}

interface IERC1155Errors {
    error ERC1155InsufficientBalance(address sender, uint256 balance, uint256 needed, uint256 tokenId);
    error ERC1155InvalidSender(address sender);
    error ERC1155InvalidReceiver(address receiver);
    error ERC1155MissingApprovalForAll(address operator, address owner);
    error ERC1155InvalidApprover(address approver);
    error ERC1155InvalidOperator(address operator);
    error ERC1155InvalidArrayLength(uint256 idsLength, uint256 valuesLength);
}

abstract contract ERC20 is Context, IERC20, IERC20Metadata, IERC20Errors {
    mapping(address account => uint256) private _balances;
    mapping(address account => mapping(address spender => uint256)) private _allowances;
    uint256 private _totalSupply;
    string private _name;
    string private _symbol;

    constructor(string memory name_, string memory symbol_) {
        _name = name_;
        _symbol = symbol_;
    }

    function name() public view virtual returns (string memory) { return _name; }
    function symbol() public view virtual returns (string memory) { return _symbol; }
    function decimals() public view virtual returns (uint8) { return 18; }
    function totalSupply() public view virtual returns (uint256) { return _totalSupply; }
    function balanceOf(address account) public view virtual returns (uint256) { return _balances[account]; }

    function transfer(address to, uint256 value) public virtual returns (bool) {
        address owner = _msgSender();
        _transfer(owner, to, value);
        return true;
    }

    function allowance(address owner, address spender) public view virtual returns (uint256) {
        return _allowances[owner][spender];
    }

    function approve(address spender, uint256 value) public virtual returns (bool) {
        address owner = _msgSender();
        _approve(owner, spender, value);
        return true;
    }

    function transferFrom(address from, address to, uint256 value) public virtual returns (bool) {
        address spender = _msgSender();
        _spendAllowance(from, spender, value);
        _transfer(from, to, value);
        return true;
    }

    function _transfer(address from, address to, uint256 value) internal {
        if (from == address(0)) revert ERC20InvalidSender(address(0));
        if (to == address(0)) revert ERC20InvalidReceiver(address(0));
        _update(from, to, value);
    }

    function _update(address from, address to, uint256 value) internal virtual {
        if (from == address(0)) {
            _totalSupply += value;
        } else {
            uint256 fromBalance = _balances[from];
            if (fromBalance < value) revert ERC20InsufficientBalance(from, fromBalance, value);
            unchecked { _balances[from] = fromBalance - value; }
        }
        if (to == address(0)) {
            unchecked { _totalSupply -= value; }
        } else {
            unchecked { _balances[to] += value; }
        }
        emit Transfer(from, to, value);
    }

    function _mint(address account, uint256 value) internal {
        if (account == address(0)) revert ERC20InvalidReceiver(address(0));
        _update(address(0), account, value);
    }

    function _burn(address account, uint256 value) internal {
        if (account == address(0)) revert ERC20InvalidSender(address(0));
        _update(account, address(0), value);
    }

    function _approve(address owner, address spender, uint256 value) internal {
        _approve(owner, spender, value, true);
    }

    function _approve(address owner, address spender, uint256 value, bool emitEvent) internal virtual {
        if (owner == address(0)) revert ERC20InvalidApprover(address(0));
        if (spender == address(0)) revert ERC20InvalidSpender(address(0));
        _allowances[owner][spender] = value;
        if (emitEvent) emit Approval(owner, spender, value);
    }

    function _spendAllowance(address owner, address spender, uint256 value) internal virtual {
        uint256 currentAllowance = allowance(owner, spender);
        if (currentAllowance < type(uint256).max) {
            if (currentAllowance < value) revert ERC20InsufficientAllowance(spender, currentAllowance, value);
            unchecked { _approve(owner, spender, currentAllowance - value, false); }
        }
    }
}

abstract contract ERC20Burnable is Context, ERC20 {
    function burn(uint256 value) public virtual { _burn(_msgSender(), value); }
    function burnFrom(address account, uint256 value) public virtual {
        _spendAllowance(account, _msgSender(), value);
        _burn(account, value);
    }
}

abstract contract Pausable is Context {
    bool private _paused;
    event Paused(address account);
    event Unpaused(address account);
    error EnforcedPause();
    error ExpectedPause();

    modifier whenNotPaused() { _requireNotPaused(); _; }
    modifier whenPaused() { _requirePaused(); _; }

    function paused() public view virtual returns (bool) { return _paused; }
    function _requireNotPaused() internal view virtual { if (paused()) revert EnforcedPause(); }
    function _requirePaused() internal view virtual { if (!paused()) revert ExpectedPause(); }

    function _pause() internal virtual whenNotPaused { _paused = true; emit Paused(_msgSender()); }
    function _unpause() internal virtual whenPaused { _paused = false; emit Unpaused(_msgSender()); }
}

abstract contract ERC20Pausable is ERC20, Pausable {
    function _update(address from, address to, uint256 value) internal virtual override whenNotPaused {
        super._update(from, to, value);
    }
}

interface IAccessControl {
    error AccessControlUnauthorizedAccount(address account, bytes32 neededRole);
    error AccessControlBadConfirmation();
    event RoleAdminChanged(bytes32 indexed role, bytes32 indexed previousAdminRole, bytes32 indexed newAdminRole);
    event RoleGranted(bytes32 indexed role, address indexed account, address indexed sender);
    event RoleRevoked(bytes32 indexed role, address indexed account, address indexed sender);
    function hasRole(bytes32 role, address account) external view returns (bool);
    function getRoleAdmin(bytes32 role) external view returns (bytes32);
    function grantRole(bytes32 role, address account) external;
    function revokeRole(bytes32 role, address account) external;
    function renounceRole(bytes32 role, address callerConfirmation) external;
}

interface IERC165 {
    function supportsInterface(bytes4 interfaceId) external view returns (bool);
}

abstract contract ERC165 is IERC165 {
    function supportsInterface(bytes4 interfaceId) public view virtual returns (bool) {
        return interfaceId == type(IERC165).interfaceId;
    }
}

abstract contract AccessControl is Context, IAccessControl, ERC165 {
    struct RoleData {
        mapping(address account => bool) hasRole;
        bytes32 adminRole;
    }
    mapping(bytes32 role => RoleData) private _roles;
    bytes32 public constant DEFAULT_ADMIN_ROLE = 0x00;

    modifier onlyRole(bytes32 role) { _checkRole(role); _; }

    function supportsInterface(bytes4 interfaceId) public view virtual override returns (bool) {
        return interfaceId == type(IAccessControl).interfaceId || super.supportsInterface(interfaceId);
    }

    function hasRole(bytes32 role, address account) public view virtual returns (bool) {
        return _roles[role].hasRole[account];
    }

    function _checkRole(bytes32 role) internal view virtual { _checkRole(role, _msgSender()); }

    function _checkRole(bytes32 role, address account) internal view virtual {
        if (!hasRole(role, account)) revert AccessControlUnauthorizedAccount(account, role);
    }

    function getRoleAdmin(bytes32 role) public view virtual returns (bytes32) {
        return _roles[role].adminRole;
    }

    function grantRole(bytes32 role, address account) public virtual onlyRole(getRoleAdmin(role)) {
        _grantRole(role, account);
    }

    function revokeRole(bytes32 role, address account) public virtual onlyRole(getRoleAdmin(role)) {
        _revokeRole(role, account);
    }

    function renounceRole(bytes32 role, address callerConfirmation) public virtual {
        if (callerConfirmation != _msgSender()) revert AccessControlBadConfirmation();
        _revokeRole(role, callerConfirmation);
    }

    function _setRoleAdmin(bytes32 role, bytes32 adminRole) internal virtual {
        bytes32 previousAdminRole = getRoleAdmin(role);
        _roles[role].adminRole = adminRole;
        emit RoleAdminChanged(role, previousAdminRole, adminRole);
    }

    function _grantRole(bytes32 role, address account) internal virtual returns (bool) {
        if (!hasRole(role, account)) {
            _roles[role].hasRole[account] = true;
            emit RoleGranted(role, account, _msgSender());
            return true;
        }
        return false;
    }

    function _revokeRole(bytes32 role, address account) internal virtual returns (bool) {
        if (hasRole(role, account)) {
            _roles[role].hasRole[account] = false;
            emit RoleRevoked(role, account, _msgSender());
            return true;
        }
        return false;
    }
}

/**
 * @title M1Token — Al Shumookh M1 Fund Token
 * @notice Reserve-backed token representing the M1 Fund.
 */
contract M1Token is ERC20, ERC20Burnable, ERC20Pausable, AccessControl {

    bytes32 public constant MINTER_ROLE          = keccak256("MINTER_ROLE");
    bytes32 public constant PAUSER_ROLE          = keccak256("PAUSER_ROLE");
    bytes32 public constant RESERVE_MANAGER_ROLE = keccak256("RESERVE_MANAGER_ROLE");

    uint256 public maxSupply;
    uint256 public totalReserveUSDCents;
    uint256 public lastReserveUpdateAt;

    event MaxSupplyUpdated(uint256 oldMaxSupply, uint256 newMaxSupply);
    event ReserveUpdated(uint256 oldReserveUSDCents, uint256 newReserveUSDCents, string source);
    event MintedWithReserve(address indexed to, uint256 amount, uint256 reserveAddedUSDCents);

    constructor(address admin, uint256 initialMaxSupply)
        ERC20("Al Shumookh M1 Fund Token", "M1")
    {
        require(admin != address(0), "Invalid admin");
        require(initialMaxSupply > 0, "Invalid max supply");
        maxSupply = initialMaxSupply * 10 ** decimals();
        _grantRole(DEFAULT_ADMIN_ROLE,   admin);
        _grantRole(MINTER_ROLE,          admin);
        _grantRole(PAUSER_ROLE,          admin);
        _grantRole(RESERVE_MANAGER_ROLE, admin);
    }

    function mint(address to, uint256 amount) external onlyRole(MINTER_ROLE) {
        require(totalSupply() + amount <= maxSupply, "Max supply exceeded");
        _mint(to, amount);
    }

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
        totalReserveUSDCents += reserveAddedUSDCents;
        lastReserveUpdateAt   = block.timestamp;
        emit MintedWithReserve(to, amount, reserveAddedUSDCents);
        emit ReserveUpdated(oldReserve, totalReserveUSDCents, source);
    }

    function updateReserve(
        uint256 newTotalReserveUSDCents,
        string calldata source
    ) external onlyRole(RESERVE_MANAGER_ROLE) {
        uint256 old = totalReserveUSDCents;
        totalReserveUSDCents = newTotalReserveUSDCents;
        lastReserveUpdateAt  = block.timestamp;
        emit ReserveUpdated(old, newTotalReserveUSDCents, source);
    }

    function reservePerTokenCents() external view returns (uint256) {
        if (totalSupply() == 0) return 0;
        return (totalReserveUSDCents * 10 ** decimals()) / totalSupply();
    }

    function backingRatioBps() external view returns (uint256) {
        if (totalSupply() == 0) return 0;
        uint256 supplyInCents = totalSupply() / 10 ** (decimals() - 2);
        if (supplyInCents == 0) return 0;
        return (totalReserveUSDCents * 10_000) / supplyInCents;
    }

    function setMaxSupply(uint256 newMaxSupply) external onlyRole(DEFAULT_ADMIN_ROLE) {
        uint256 newMax = newMaxSupply * 10 ** decimals();
        require(newMax >= totalSupply(), "Below current supply");
        uint256 old = maxSupply;
        maxSupply = newMax;
        emit MaxSupplyUpdated(old, newMax);
    }

    function pause()   external onlyRole(PAUSER_ROLE) { _pause(); }
    function unpause() external onlyRole(PAUSER_ROLE) { _unpause(); }

    function _update(address from, address to, uint256 value)
        internal
        override(ERC20, ERC20Pausable)
    {
        super._update(from, to, value);
    }
}
