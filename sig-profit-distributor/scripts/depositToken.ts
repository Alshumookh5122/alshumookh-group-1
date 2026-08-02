import { ethers } from "hardhat";
import * as dotenv from "dotenv";
dotenv.config();

async function main() {
  const distAddr = process.env.DISTRIBUTOR_ADDRESS;
  const tokenAddr = process.env.TOKEN_ADDRESS;
  const amountRaw = process.env.DEPOSIT_AMOUNT;
  if (!distAddr) throw new Error("DISTRIBUTOR_ADDRESS not set");
  if (!tokenAddr) throw new Error("TOKEN_ADDRESS not set");
  if (!amountRaw) throw new Error("DEPOSIT_AMOUNT not set");

  const amount = BigInt(amountRaw);
  const token = await ethers.getContractAt("IERC20", tokenAddr);
  const dist = await ethers.getContractAt("SIGProfitDistributor", distAddr);

  console.log(`Approving ${amount} tokens for distributor...`);
  const approveTx = await (token as any).approve(distAddr, amount);
  await approveTx.wait();
  console.log(`Approved. Tx: ${approveTx.hash}`);

  console.log(`Depositing ${amount} of token ${tokenAddr}...`);
  const tx = await dist.depositToken(tokenAddr, amount);
  await tx.wait();
  console.log(`Deposited. Tx: ${tx.hash}`);
  console.log(`   totalReceived = ${await dist.totalReceived(tokenAddr)}`);
}

main().catch((err) => { console.error(err); process.exitCode = 1; });
