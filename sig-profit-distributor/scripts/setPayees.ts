import { ethers } from "hardhat";
import * as dotenv from "dotenv";
dotenv.config();

async function main() {
  const distAddr = process.env.DISTRIBUTOR_ADDRESS;
  if (!distAddr) throw new Error("DISTRIBUTOR_ADDRESS not set in .env");

  const payeesRaw = process.env.PAYEES_JSON;
  const sharesRaw = process.env.SHARES_JSON;
  if (!payeesRaw || !sharesRaw) throw new Error("PAYEES_JSON or SHARES_JSON not set in .env");

  const payees: string[] = JSON.parse(payeesRaw);
  const shares: number[] = JSON.parse(sharesRaw);

  const sum = shares.reduce((a, b) => a + b, 0);
  if (sum !== 10000) throw new Error(`Shares sum ${sum} !== 10000`);

  const dist = await ethers.getContractAt("SIGProfitDistributor", distAddr);
  console.log(`Setting payees on ${distAddr}...`);
  const tx = await dist.setPayees(payees, shares);
  await tx.wait();
  console.log(`setPayees tx: ${tx.hash}`);
  for (let i = 0; i < payees.length; i++) {
    console.log(`   ${payees[i]} => ${shares[i]} BPS (${shares[i] / 100}%)`);
  }
}

main().catch((err) => { console.error(err); process.exitCode = 1; });
