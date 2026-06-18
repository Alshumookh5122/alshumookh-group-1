import { ethers } from "hardhat";
import * as dotenv from "dotenv";
dotenv.config();

async function main() {
  const distAddr = process.env.DISTRIBUTOR_ADDRESS;
  if (!distAddr) throw new Error("DISTRIBUTOR_ADDRESS not set in .env");

  const dist = await ethers.getContractAt("SIGProfitDistributor", distAddr);
  console.log(`Freezing shares on ${distAddr}...`);
  const tx = await dist.freezeShares();
  await tx.wait();
  console.log(`freezeShares tx: ${tx.hash}`);
  console.log(`   sharesFrozen = ${await dist.sharesFrozen()}`);
}

main().catch((err) => { console.error(err); process.exitCode = 1; });
