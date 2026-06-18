import { ethers } from "hardhat";
import * as dotenv from "dotenv";
dotenv.config();

async function main() {
  const initialOwner = process.env.INITIAL_OWNER;
  if (!initialOwner) throw new Error("INITIAL_OWNER not set in .env");

  console.log("Deploying SIGProfitDistributor...");
  const Factory = await ethers.getContractFactory("SIGProfitDistributor");
  const dist = await Factory.deploy(initialOwner);
  await dist.waitForDeployment();

  const addr = await dist.getAddress();
  console.log(`SIGProfitDistributor deployed to: ${addr}`);
  console.log(`   Owner: ${initialOwner}`);
  console.log(`\nTo verify on BscScan:`);
  console.log(`npx hardhat verify --network bscTestnet ${addr} "${initialOwner}"`);
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
