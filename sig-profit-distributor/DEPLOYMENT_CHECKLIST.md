# SIGProfitDistributor — Deployment Checklist

Use this checklist for every deployment. Check off each item before moving to the next phase.

---

## Phase 1 — Before Deployment

- [ ] Confirm target network (BSC Testnet for staging, BSC Mainnet for production)
- [ ] Confirm deployer wallet has enough BNB for gas (minimum 0.05 BNB recommended)
- [ ] Confirm `INITIAL_OWNER` address is correct — this wallet will control the contract
- [ ] Confirm `INITIAL_OWNER` is a hardware wallet or multi-sig for mainnet deployments
- [ ] Confirm all payee addresses are final and verified (no typos)
- [ ] Confirm BPS shares are correct and sum to exactly 10 000
      Example: [4000, 3000, 3000] = 40% + 30% + 30% = 100%
- [ ] Run the full test suite locally and confirm all tests pass:
      `npx hardhat test`
- [ ] Review `SIGProfitDistributor.sol` source code one final time
- [ ] Confirm OpenZeppelin version in `package.json` matches the import paths in the contract
- [ ] Copy `.env.example` to `.env` and fill in all required values
- [ ] Double-check `PRIVATE_KEY` in `.env` — never commit this file to git

---

## Phase 2 — After Deployment

- [ ] Record the deployed contract address in a safe location
- [ ] Copy the address into `.env` as `DISTRIBUTOR_ADDRESS`
- [ ] Verify the contract on BscScan:
      `npx hardhat verify --network bscTestnet <ADDRESS> "<OWNER>"`
- [ ] Confirm BscScan shows the contract as "Verified" with correct source code
- [ ] Run `setPayees` script and confirm transaction succeeds:
      `npx hardhat run scripts/setPayees.ts --network bscTestnet`
- [ ] Read back payees from the contract and verify each address and BPS share:
      Call `payees()`, `payeeCount()`, `shareBps(address)` on BscScan or via script
- [ ] Confirm all shares sum to 10 000 BPS on-chain
- [ ] Run `freezeShares` script:
      `npx hardhat run scripts/freezeShares.ts --network bscTestnet`
- [ ] Confirm `sharesFrozen` returns `true` on-chain
- [ ] Send a small test deposit (e.g. 0.001 BNB) via `depositNative()`
- [ ] Confirm `totalReceived(address(0))` increased correctly
- [ ] Have one payee call `claimNative()` from their wallet
- [ ] Confirm the payee received the correct BNB amount (pro-rata of test deposit)
- [ ] Repeat test deposit and claim for at least one BEP20 token
- [ ] Save all transaction hashes (deploy, setPayees, freezeShares, test deposit, test claim)
- [ ] Share contract address with all payees and provide BscScan link

---

## Phase 3 — When an Investor Exits / Agreement Ends

- [ ] Confirm all parties agree the current distribution period is ending
- [ ] Run `closeDeposits` script:
      `npx hardhat run scripts/closeDeposits.ts --network bscTestnet`
- [ ] Confirm `depositsClosed` returns `true` on-chain
- [ ] Confirm that sending BNB to the contract now reverts
- [ ] Do NOT deposit any new revenue into this contract
- [ ] Inform all investors and payees that:
      - This contract is now closed to new deposits
      - Their existing unclaimed balance is still claimable and will remain so indefinitely
      - They should claim any remaining balance at their convenience
- [ ] Call `trackedBalance(address(0))` and `trackedBalance(tokenAddress)` to see remaining unclaimed funds
- [ ] Deploy a NEW `SIGProfitDistributor` contract for the next investor agreement
- [ ] Set new payees and shares on the new contract
- [ ] Freeze shares on the new contract
- [ ] Route all future deposits to the new contract address
- [ ] Update all internal systems and documentation with the new contract address
- [ ] Announce the new contract address to all stakeholders
