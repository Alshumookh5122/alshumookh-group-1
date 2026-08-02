import { ethers } from "hardhat";
import * as dotenv from "dotenv";
dotenv.config();

async function main() {
  const distAddr = process.env.DISTRIBUTOR_ADDRESS;
  if (!distAddr) throw new Error("DISTRIBUTOR_ADDRESS not set in .env");

  const dist = await ethers.getContractAt("SIGProfitDistributor", distAddr);
  console.log(`Closing deposits on ${distAddr}...`);
  const tx = await dist.closeDeposits();
  await tx.wait();
  console.log(`closeDeposits tx: ${tx.hash}`);
  console.log(`   depositsClosed = ${await dist.depositsClosed()}`);
  console.log(`\nWARNING: Deploy a NEW SIGProfitDistributor for future revenue.`);
  console.log(`   Investors can still claim their old balance from this contract.`);
}

main().catch((err) => { console.error(err); process.exitCode = 1; });
