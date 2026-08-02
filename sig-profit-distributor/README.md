# SIGProfitDistributor — Hardhat TypeScript Project

Pull-payment profit distribution smart contract for the SIG / Al Shumookh project.
Receives BNB (native) and BEP20 tokens, then lets registered investors claim their
pro-rata share at any time without any mass-payout loops.

---

## Contract Architecture

```
SIGProfitDistributor
├── Inherits: Ownable2Step, ReentrancyGuard (OpenZeppelin v5)
├── Setup Phase
│   ├── setPayees(accounts[], bpsValues[])   — owner only, before freeze
│   └── freezeShares()                        — owner only, permanent
├── Deposit Phase (requires sharesFrozen = true)
│   ├── depositNative() / receive()           — anyone, BNB
│   └── depositToken(token, amount)           — anyone, BEP20
├── Claim Phase (always open after freeze)
│   ├── claimNative() / claimNativeFor(payee)
│   └── claimToken(token) / claimTokenFor(token, payee)
├── Close Phase (optional)
│   └── closeDeposits()                       — owner only, stops new deposits
│                                               claims remain open forever
└── Rescue (untracked funds only)
    ├── rescueUntrackedNative(to, amount)
    └── rescueUntrackedToken(token, to, amount)
```

---

## Security Features

- **Pull payment pattern**: no loops over payee arrays during payouts, eliminating gas-bomb risk.
- **Ownable2Step**: ownership transfer requires the new owner to accept, preventing accidental transfers.
- **ReentrancyGuard**: all state-changing external functions are protected.
- **SafeERC20**: uses OpenZeppelin's SafeERC20 for all token transfers.
- **Fee-on-transfer support**: depositToken uses before/after balance accounting.
- **Rescue cannot touch tracked funds**: untracked = currentBalance - trackedBalance; rescue is capped to that.
- **Custom errors**: gas-efficient reverts with descriptive names.
- **No upgradability**: immutable logic — what you deploy is what you get.
- **No admin withdrawal**: owner cannot withdraw investor funds, only truly untracked funds.
- **Shares frozen before deposits**: enforces correct setup order at the contract level.
- **Duplicate payee check**: reverts on duplicate addresses in setPayees.
- **BPS sum check**: reverts unless shares sum exactly to 10 000.

---

## Quick Start

### 1. Install dependencies

```bash
cd sig-profit-distributor
npm install
```

### 2. Copy and fill environment file

```bash
cp .env.example .env
# Edit .env and fill in PRIVATE_KEY, RPC_URL, BSCSCAN_API_KEY, INITIAL_OWNER
```

### 3. Compile

```bash
npm run compile
# or
npx hardhat compile
```

TypeChain types are generated automatically into `typechain-types/`.

### 4. Run tests

```bash
npm test
# or
npx hardhat test
```

All 47 tests should pass on the local Hardhat network (no external node needed).

### 5. Gas report

```bash
REPORT_GAS=true npx hardhat test
```

---

## Deployment

### Deploy to BSC Testnet

```bash
# Make sure .env has PRIVATE_KEY, RPC_URL, INITIAL_OWNER
npx hardhat run scripts/deploy.ts --network bscTestnet
```

The script prints the deployed address. Copy it into `.env` as `DISTRIBUTOR_ADDRESS`.

### Deploy to BSC Mainnet

```bash
npx hardhat run scripts/deploy.ts --network bscMainnet
```

---

## Post-Deployment Setup

### Step 1 — Set payees

Edit `.env`:
```
PAYEES_JSON=["0xInvestor1","0xInvestor2","0xCompany"]
SHARES_JSON=[4000,3000,3000]
```

Run:
```bash
npx hardhat run scripts/setPayees.ts --network bscTestnet
```

Shares must sum to exactly 10 000 BPS (100%). See the BPS table below.

### Step 2 — Freeze shares

Once the payee list is correct, permanently lock it:
```bash
npx hardhat run scripts/freezeShares.ts --network bscTestnet
```

This cannot be undone. After this point no payee changes are possible.

### Step 3 — Deposit BNB

Send BNB directly to the contract address, or call `depositNative()` — both work.

### Step 4 — Deposit BEP20 tokens (e.g. SIG or USDT)

```bash
# Set TOKEN_ADDRESS and DEPOSIT_AMOUNT in .env first
npx hardhat run scripts/depositToken.ts --network bscTestnet
```

### Step 5 — Investors claim their share

Each investor calls `claimNative()` or `claimToken(tokenAddress)` directly from their wallet,
or a relayer calls `claimNativeFor(payee)` / `claimTokenFor(token, payee)`.
Funds always go to the payee address, never to the caller.

---

## BscScan Verification

```bash
npx hardhat verify --network bscTestnet <DEPLOYED_ADDRESS> "<INITIAL_OWNER_ADDRESS>"
npx hardhat verify --network bscMainnet <DEPLOYED_ADDRESS> "<INITIAL_OWNER_ADDRESS>"
```

---

## Close Deposits (End of Investor Agreement)

When an investor agreement ends:

```bash
npx hardhat run scripts/closeDeposits.ts --network bscTestnet
```

- New deposits are blocked immediately.
- All previously deposited funds remain claimable by payees forever — this contract is NOT abandoned.
- Deploy a fresh `SIGProfitDistributor` for future profits with new investor terms.

---

## How Claims Work — Pull Payment Formula

For each asset (native or token), the contract tracks:

```
totalReceived[asset]          — total ever deposited
_claimed[asset][payee]        — total ever claimed by a specific payee
```

When a payee calls claim:

```
entitled    = totalReceived[asset] * shareBps[payee] / 10_000
claimable   = entitled - _claimed[asset][payee]
```

This means:
- A payee who has never claimed gets their full share of everything deposited so far.
- A payee who claimed last month only gets the share of new deposits since then.
- There is no concept of "rounds" or "epochs" — it is a continuous accumulator.

Example: 10 BNB deposited, payee has 30% share, has claimed 2 BNB:
```
entitled  = 10 * 3000 / 10000 = 3 BNB
claimable = 3 - 2 = 1 BNB
```

---

## How to Close Deposits Without Blocking Claims

1. Call `closeDeposits()` — sets `depositsClosed = true`.
2. `depositNative()` and `depositToken()` now revert with `DepositsAreClosed`.
3. `claimNative()`, `claimToken()`, `claimNativeFor()`, `claimTokenFor()` continue to work.
4. Payees can claim their balance from this contract indefinitely.
5. Deploy a new `SIGProfitDistributor` for any future revenue stream.

---

## BPS (Basis Points) Reference Table

| BPS   | Percentage |
|-------|------------|
| 10000 | 100.00 %   |
| 7000  | 70.00 %    |
| 5000  | 50.00 %    |
| 3000  | 30.00 %    |
| 2500  | 25.00 %    |
| 2000  | 20.00 %    |
| 1000  | 10.00 %    |
| 500   | 5.00 %     |
| 100   | 1.00 %     |
| 50    | 0.50 %     |
| 1     | 0.01 %     |

All payee BPS values must sum to exactly 10 000.

---

## Initial DEX Price Calculation — 1 SIG = 1 USDT

To list SIG on a DEX (PancakeSwap, etc.) at an initial price of 1 SIG = 1 USDT,
the liquidity pool must be seeded with equal value of SIG tokens and USDT.

### Formula

```
Price = USDT liquidity / SIG liquidity
```

To achieve Price = 1.00 USDT per SIG:

```
USDT in pool = SIG tokens in pool
```

### Examples

| SIG tokens added to pool | USDT added to pool | Initial price |
|--------------------------|-------------------|---------------|
| 100,000 SIG              | 100,000 USDT      | $1.00         |
| 1,000,000 SIG            | 1,000,000 USDT    | $1.00         |
| 10,000,000 SIG           | 10,000,000 USDT   | $1.00         |
| 10,000,000,000 SIG       | 10,000,000,000 USDT | $1.00       |

The price is determined entirely by the ratio of tokens in the pool, not the absolute amounts.
Adding more liquidity at a 1:1 ratio does not change the price — it only increases depth.

### FDV Warning

Fully Diluted Valuation (FDV) is a theoretical metric:

```
FDV = Total Supply * Price
```

| Total SIG Supply    | Launch Price | FDV (theoretical) |
|--------------------|-------------|-------------------|
| 100,000            | $1.00       | $100,000          |
| 1,000,000          | $1.00       | $1,000,000        |
| 10,000,000         | $1.00       | $10,000,000       |
| 10,000,000,000     | $1.00       | $10,000,000,000   |

A 10 billion supply at $1.00 implies a $10 billion FDV. This is a theoretical number only.
It does NOT mean the project is worth $10 billion. Real market cap is determined by
actual circulating supply multiplied by market price. Tokens not yet sold or in
the liquidity pool do not represent real capital. Always communicate this clearly
to investors.

---

## Contract Files

```
sig-profit-distributor/
├── contracts/
│   ├── SIGProfitDistributor.sol   — Main contract
│   └── mocks/
│       └── MockERC20.sol          — Test-only mintable ERC20
├── scripts/
│   ├── deploy.ts                  — Deploy distributor
│   ├── setPayees.ts               — Register payees from .env
│   ├── freezeShares.ts            — Lock payee list
│   ├── closeDeposits.ts           — Stop accepting deposits
│   └── depositToken.ts            — Deposit BEP20 tokens
├── test/
│   └── SIGProfitDistributor.test.ts — Full test suite (47 tests)
├── hardhat.config.ts
├── tsconfig.json
├── package.json
├── .env.example
├── README.md
└── DEPLOYMENT_CHECKLIST.md
```
