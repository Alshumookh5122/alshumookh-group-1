import { expect } from "chai";
import { ethers } from "hardhat";
import { SignerWithAddress } from "@nomicfoundation/hardhat-ethers/signers";
import {
  SIGProfitDistributor,
  MockERC20,
} from "../typechain-types";

const BPS = 10_000n;
const ZERO_ADDRESS = ethers.ZeroAddress;

async function deployDistributor(owner: SignerWithAddress): Promise<SIGProfitDistributor> {
  const Factory = await ethers.getContractFactory("SIGProfitDistributor", owner);
  return (await Factory.deploy(owner.address)) as unknown as SIGProfitDistributor;
}

async function deployToken(name: string, symbol: string, decimals: number): Promise<MockERC20> {
  const Factory = await ethers.getContractFactory("MockERC20");
  return (await Factory.deploy(name, symbol, decimals)) as unknown as MockERC20;
}

describe("SIGProfitDistributor", function () {
  let owner: SignerWithAddress;
  let alice: SignerWithAddress;
  let bob: SignerWithAddress;
  let carol: SignerWithAddress;
  let dist: SIGProfitDistributor;
  let usdt: MockERC20;

  beforeEach(async () => {
    [owner, alice, bob, carol] = await ethers.getSigners();
    dist = await deployDistributor(owner);
    usdt = await deployToken("Mock USDT", "USDT", 18);
  });

  // ---------------------------------------------------------------------------
  // Deployment
  // ---------------------------------------------------------------------------
  describe("Deployment", () => {
    it("deploys with valid owner", async () => {
      expect(await dist.owner()).to.equal(owner.address);
    });

    it("reverts if initialOwner is zero", async () => {
      const Factory = await ethers.getContractFactory("SIGProfitDistributor");
      await expect(Factory.deploy(ZERO_ADDRESS)).to.be.revertedWithCustomError(
        dist,
        "InvalidInput"
      );
    });

    it("starts with sharesFrozen=false and depositsClosed=false", async () => {
      expect(await dist.sharesFrozen()).to.be.false;
      expect(await dist.depositsClosed()).to.be.false;
    });
  });

  // ---------------------------------------------------------------------------
  // setPayees
  // ---------------------------------------------------------------------------
  describe("setPayees", () => {
    it("owner can set payees before freeze", async () => {
      await dist.setPayees([alice.address, bob.address], [7000, 3000]);
      expect(await dist.payeeCount()).to.equal(2);
      expect(await dist.shareBps(alice.address)).to.equal(7000);
      expect(await dist.shareBps(bob.address)).to.equal(3000);
    });

    it("emits PayeesSet event", async () => {
      await expect(dist.setPayees([alice.address, bob.address], [7000, 3000]))
        .to.emit(dist, "PayeesSet")
        .withArgs([alice.address, bob.address], [7000, 3000]);
    });

    it("non-owner cannot set payees", async () => {
      await expect(
        dist.connect(carol).setPayees([alice.address], [10000])
      ).to.be.revertedWithCustomError(dist, "OwnableUnauthorizedAccount");
    });

    it("reverts if arrays length mismatch", async () => {
      await expect(
        dist.setPayees([alice.address, bob.address], [10000])
      ).to.be.revertedWithCustomError(dist, "InvalidInput");
    });

    it("reverts if empty arrays", async () => {
      await expect(dist.setPayees([], [])).to.be.revertedWithCustomError(
        dist,
        "InvalidInput"
      );
    });

    it("reverts if more than 100 payees", async () => {
      const addrs: string[] = [];
      const shares: number[] = [];
      for (let i = 0; i < 101; i++) {
        addrs.push(ethers.Wallet.createRandom().address);
        shares.push(100);
      }
      await expect(
        dist.setPayees(addrs, shares)
      ).to.be.revertedWithCustomError(dist, "InvalidInput");
    });

    it("reverts if zero address in accounts", async () => {
      await expect(
        dist.setPayees([ZERO_ADDRESS], [10000])
      ).to.be.revertedWithCustomError(dist, "InvalidPayee");
    });

    it("reverts if zero share", async () => {
      await expect(
        dist.setPayees([alice.address, bob.address], [10000, 0])
      ).to.be.revertedWithCustomError(dist, "InvalidInput");
    });

    it("reverts if duplicate payee", async () => {
      await expect(
        dist.setPayees([alice.address, alice.address], [5000, 5000])
      ).to.be.revertedWithCustomError(dist, "InvalidPayee");
    });

    it("reverts if total shares != 10000", async () => {
      await expect(
        dist.setPayees([alice.address, bob.address], [6000, 3000])
      ).to.be.revertedWithCustomError(dist, "InvalidInput");
    });

    it("can replace payees before freeze", async () => {
      await dist.setPayees([alice.address], [10000]);
      await dist.setPayees([alice.address, bob.address], [7000, 3000]);
      expect(await dist.payeeCount()).to.equal(2);
    });

    it("cannot set payees after freeze", async () => {
      await dist.setPayees([alice.address], [10000]);
      await dist.freezeShares();
      await expect(
        dist.setPayees([alice.address], [10000])
      ).to.be.revertedWithCustomError(dist, "SharesAlreadyFrozen");
    });
  });

  // ---------------------------------------------------------------------------
  // freezeShares
  // ---------------------------------------------------------------------------
  describe("freezeShares", () => {
    it("owner can freeze after payees are set", async () => {
      await dist.setPayees([alice.address], [10000]);
      await expect(dist.freezeShares()).to.emit(dist, "SharesFrozen");
      expect(await dist.sharesFrozen()).to.be.true;
    });

    it("non-owner cannot freeze", async () => {
      await dist.setPayees([alice.address], [10000]);
      await expect(
        dist.connect(carol).freezeShares()
      ).to.be.revertedWithCustomError(dist, "OwnableUnauthorizedAccount");
    });

    it("cannot freeze with no payees", async () => {
      await expect(dist.freezeShares()).to.be.revertedWithCustomError(
        dist,
        "InvalidInput"
      );
    });

    it("cannot freeze twice", async () => {
      await dist.setPayees([alice.address], [10000]);
      await dist.freezeShares();
      await expect(dist.freezeShares()).to.be.revertedWithCustomError(
        dist,
        "SharesAlreadyFrozen"
      );
    });
  });

  // ---------------------------------------------------------------------------
  // Native Deposits
  // ---------------------------------------------------------------------------
  describe("Native deposits", () => {
    beforeEach(async () => {
      await dist.setPayees([alice.address, bob.address], [7000, 3000]);
    });

    it("reverts deposit before freeze", async () => {
      await expect(
        dist.depositNative({ value: ethers.parseEther("1") })
      ).to.be.revertedWithCustomError(dist, "SharesNotFrozen");
    });

    it("accepts native deposit after freeze", async () => {
      await dist.freezeShares();
      const amount = ethers.parseEther("1");
      await expect(dist.depositNative({ value: amount }))
        .to.emit(dist, "NativeDeposited")
        .withArgs(owner.address, amount);
      expect(await dist.totalReceived(ZERO_ADDRESS)).to.equal(amount);
    });

    it("accepts native via receive()", async () => {
      await dist.freezeShares();
      const amount = ethers.parseEther("0.5");
      await owner.sendTransaction({ to: await dist.getAddress(), value: amount });
      expect(await dist.totalReceived(ZERO_ADDRESS)).to.equal(amount);
    });

    it("rejects zero native deposit", async () => {
      await dist.freezeShares();
      await expect(
        dist.depositNative({ value: 0 })
      ).to.be.revertedWithCustomError(dist, "InvalidInput");
    });

    it("rejects native deposit after closeDeposits", async () => {
      await dist.freezeShares();
      await dist.closeDeposits();
      await expect(
        dist.depositNative({ value: ethers.parseEther("1") })
      ).to.be.revertedWithCustomError(dist, "DepositsAreClosed");
    });

    it("totalReceived updates correctly on multiple deposits", async () => {
      await dist.freezeShares();
      await dist.depositNative({ value: ethers.parseEther("1") });
      await dist.depositNative({ value: ethers.parseEther("2") });
      expect(await dist.totalReceived(ZERO_ADDRESS)).to.equal(ethers.parseEther("3"));
    });
  });

  // ---------------------------------------------------------------------------
  // ERC20 Deposits
  // ---------------------------------------------------------------------------
  describe("ERC20 deposits", () => {
    const DEPOSIT = ethers.parseUnits("1000", 18);

    beforeEach(async () => {
      await dist.setPayees([alice.address, bob.address], [7000, 3000]);
      await usdt.mint(owner.address, ethers.parseUnits("100000", 18));
    });

    it("reverts before freeze", async () => {
      await usdt.approve(await dist.getAddress(), DEPOSIT);
      await expect(
        dist.depositToken(await usdt.getAddress(), DEPOSIT)
      ).to.be.revertedWithCustomError(dist, "SharesNotFrozen");
    });

    it("accepts token deposit after approval and freeze", async () => {
      await dist.freezeShares();
      await usdt.approve(await dist.getAddress(), DEPOSIT);
      await expect(dist.depositToken(await usdt.getAddress(), DEPOSIT))
        .to.emit(dist, "TokenDeposited")
        .withArgs(owner.address, await usdt.getAddress(), DEPOSIT);
    });

    it("records actual amount received", async () => {
      await dist.freezeShares();
      await usdt.approve(await dist.getAddress(), DEPOSIT);
      await dist.depositToken(await usdt.getAddress(), DEPOSIT);
      expect(await dist.totalReceived(await usdt.getAddress())).to.equal(DEPOSIT);
    });

    it("rejects zero token address", async () => {
      await dist.freezeShares();
      await expect(
        dist.depositToken(ZERO_ADDRESS, DEPOSIT)
      ).to.be.revertedWithCustomError(dist, "InvalidInput");
    });

    it("rejects zero amount", async () => {
      await dist.freezeShares();
      await expect(
        dist.depositToken(await usdt.getAddress(), 0)
      ).to.be.revertedWithCustomError(dist, "InvalidInput");
    });

    it("rejects after closeDeposits", async () => {
      await dist.freezeShares();
      await dist.closeDeposits();
      await usdt.approve(await dist.getAddress(), DEPOSIT);
      await expect(
        dist.depositToken(await usdt.getAddress(), DEPOSIT)
      ).to.be.revertedWithCustomError(dist, "DepositsAreClosed");
    });

    it("totalReceived(token) updates correctly", async () => {
      await dist.freezeShares();
      await usdt.approve(await dist.getAddress(), DEPOSIT * 3n);
      await dist.depositToken(await usdt.getAddress(), DEPOSIT);
      await dist.depositToken(await usdt.getAddress(), DEPOSIT * 2n);
      expect(await dist.totalReceived(await usdt.getAddress())).to.equal(DEPOSIT * 3n);
    });
  });

  // ---------------------------------------------------------------------------
  // Claims
  // ---------------------------------------------------------------------------
  describe("Claims", () => {
    const NATIVE_DEPOSIT = ethers.parseEther("10");
    const TOKEN_DEPOSIT = ethers.parseUnits("1000", 18);

    beforeEach(async () => {
      await dist.setPayees([alice.address, bob.address], [7000, 3000]);
      await dist.freezeShares();
      await dist.depositNative({ value: NATIVE_DEPOSIT });
      await usdt.mint(owner.address, TOKEN_DEPOSIT);
      await usdt.approve(await dist.getAddress(), TOKEN_DEPOSIT);
      await dist.depositToken(await usdt.getAddress(), TOKEN_DEPOSIT);
    });

    it("claimable returns correct 70/30 split for native", async () => {
      expect(await dist.claimable(ZERO_ADDRESS, alice.address)).to.equal((NATIVE_DEPOSIT * 7000n) / BPS);
      expect(await dist.claimable(ZERO_ADDRESS, bob.address)).to.equal((NATIVE_DEPOSIT * 3000n) / BPS);
    });

    it("claimable returns correct 70/30 split for token", async () => {
      const addr = await usdt.getAddress();
      expect(await dist.claimable(addr, alice.address)).to.equal((TOKEN_DEPOSIT * 7000n) / BPS);
      expect(await dist.claimable(addr, bob.address)).to.equal((TOKEN_DEPOSIT * 3000n) / BPS);
    });

    it("payee can claim native", async () => {
      const expected = (NATIVE_DEPOSIT * 7000n) / BPS;
      await expect(dist.connect(alice).claimNative())
        .to.emit(dist, "NativeClaimed")
        .withArgs(alice.address, expected)
        .and.to.changeEtherBalance(alice, expected);
    });

    it("payee can claim token", async () => {
      const addr = await usdt.getAddress();
      const expected = (TOKEN_DEPOSIT * 7000n) / BPS;
      await expect(dist.connect(alice).claimToken(addr))
        .to.emit(dist, "TokenClaimed")
        .withArgs(alice.address, addr, expected);
      expect(await usdt.balanceOf(alice.address)).to.equal(expected);
    });

    it("claim twice only claims newly available amount", async () => {
      await dist.connect(alice).claimNative();
      const extra = ethers.parseEther("5");
      await dist.depositNative({ value: extra });
      const newClaimable = await dist.claimable(ZERO_ADDRESS, alice.address);
      expect(newClaimable).to.equal((extra * 7000n) / BPS);
      await expect(dist.connect(alice).claimNative()).to.changeEtherBalance(alice, newClaimable);
    });

    it("reverts if nothing to claim (native)", async () => {
      await expect(dist.connect(carol).claimNative()).to.be.revertedWithCustomError(dist, "NothingToClaim");
    });

    it("reverts if nothing to claim (token)", async () => {
      await expect(dist.connect(carol).claimToken(await usdt.getAddress())).to.be.revertedWithCustomError(dist, "NothingToClaim");
    });

    it("claimNativeFor sends funds to payee, not caller", async () => {
      const expected = (NATIVE_DEPOSIT * 7000n) / BPS;
      await expect(dist.connect(carol).claimNativeFor(alice.address)).to.changeEtherBalance(alice, expected);
    });

    it("claimTokenFor sends funds to payee, not caller", async () => {
      const addr = await usdt.getAddress();
      const expected = (TOKEN_DEPOSIT * 7000n) / BPS;
      await dist.connect(carol).claimTokenFor(addr, alice.address);
      expect(await usdt.balanceOf(alice.address)).to.equal(expected);
      expect(await usdt.balanceOf(carol.address)).to.equal(0);
    });

    it("non-payee claimable is zero", async () => {
      expect(await dist.claimable(ZERO_ADDRESS, carol.address)).to.equal(0);
      expect(await dist.claimable(await usdt.getAddress(), carol.address)).to.equal(0);
    });
  });

  // ---------------------------------------------------------------------------
  // Close Deposits
  // ---------------------------------------------------------------------------
  describe("Close deposits", () => {
    beforeEach(async () => {
      await dist.setPayees([alice.address, bob.address], [7000, 3000]);
    });

    it("owner can close deposits after freeze", async () => {
      await dist.freezeShares();
      await expect(dist.closeDeposits()).to.emit(dist, "DepositsClosed");
      expect(await dist.depositsClosed()).to.be.true;
    });

    it("non-owner cannot close deposits", async () => {
      await dist.freezeShares();
      await expect(dist.connect(carol).closeDeposits()).to.be.revertedWithCustomError(dist, "OwnableUnauthorizedAccount");
    });

    it("cannot close before freeze", async () => {
      await expect(dist.closeDeposits()).to.be.revertedWithCustomError(dist, "SharesNotFrozen");
    });

    it("cannot close twice", async () => {
      await dist.freezeShares();
      await dist.closeDeposits();
      await expect(dist.closeDeposits()).to.be.revertedWithCustomError(dist, "DepositsAreClosed");
    });

    it("after close, native deposits fail", async () => {
      await dist.freezeShares();
      await dist.closeDeposits();
      await expect(dist.depositNative({ value: ethers.parseEther("1") })).to.be.revertedWithCustomError(dist, "DepositsAreClosed");
    });

    it("after close, native claims still work", async () => {
      await dist.freezeShares();
      await dist.depositNative({ value: ethers.parseEther("10") });
      await dist.closeDeposits();
      const expected = (ethers.parseEther("10") * 7000n) / BPS;
      await expect(dist.connect(alice).claimNative()).to.changeEtherBalance(alice, expected);
    });

    it("after close, token claims still work", async () => {
      const AMOUNT = ethers.parseUnits("1000", 18);
      await usdt.mint(owner.address, AMOUNT);
      await dist.freezeShares();
      await usdt.approve(await dist.getAddress(), AMOUNT);
      await dist.depositToken(await usdt.getAddress(), AMOUNT);
      await dist.closeDeposits();
      const expected = (AMOUNT * 7000n) / BPS;
      await dist.connect(alice).claimToken(await usdt.getAddress());
      expect(await usdt.balanceOf(alice.address)).to.equal(expected);
    });
  });

  // ---------------------------------------------------------------------------
  // Rescue
  // ---------------------------------------------------------------------------
  describe("Rescue functions", () => {
    const DEPOSIT = ethers.parseEther("5");
    const TOKEN_DEPOSIT = ethers.parseUnits("500", 18);

    beforeEach(async () => {
      await dist.setPayees([alice.address, bob.address], [7000, 3000]);
      await dist.freezeShares();
      await dist.depositNative({ value: DEPOSIT });
      await usdt.mint(owner.address, TOKEN_DEPOSIT * 2n);
      await usdt.approve(await dist.getAddress(), TOKEN_DEPOSIT);
      await dist.depositToken(await usdt.getAddress(), TOKEN_DEPOSIT);
    });

    it("cannot rescue tracked native funds", async () => {
      await expect(dist.rescueUntrackedNative(owner.address, 1n)).to.be.revertedWithCustomError(dist, "NothingToRescue");
    });

    it("cannot rescue tracked token funds", async () => {
      await expect(dist.rescueUntrackedToken(await usdt.getAddress(), owner.address, 1n)).to.be.revertedWithCustomError(dist, "NothingToRescue");
    });

    it("can rescue untracked token (sent by mistake)", async () => {
      const mistakeAmount = ethers.parseUnits("50", 18);
      await usdt.transfer(await dist.getAddress(), mistakeAmount);
      const untracked = await dist.untrackedBalance(await usdt.getAddress());
      expect(untracked).to.equal(mistakeAmount);
      const ownerBefore = await usdt.balanceOf(owner.address);
      await dist.rescueUntrackedToken(await usdt.getAddress(), owner.address, mistakeAmount);
      expect(await usdt.balanceOf(owner.address)).to.equal(ownerBefore + mistakeAmount);
    });

    it("non-owner cannot rescue", async () => {
      await expect(dist.connect(carol).rescueUntrackedNative(carol.address, 1n)).to.be.revertedWithCustomError(dist, "OwnableUnauthorizedAccount");
    });

    it("cannot rescue more than untracked token balance", async () => {
      const mistakeAmount = ethers.parseUnits("50", 18);
      await usdt.transfer(await dist.getAddress(), mistakeAmount);
      await expect(dist.rescueUntrackedToken(await usdt.getAddress(), owner.address, mistakeAmount + 1n)).to.be.revertedWithCustomError(dist, "NothingToRescue");
    });
  });

  // ---------------------------------------------------------------------------
  // View Functions
  // ---------------------------------------------------------------------------
  describe("View functions", () => {
    beforeEach(async () => {
      await dist.setPayees([alice.address, bob.address], [7000, 3000]);
      await dist.freezeShares();
      await dist.depositNative({ value: ethers.parseEther("10") });
      await usdt.mint(owner.address, ethers.parseUnits("1000", 18));
      await usdt.approve(await dist.getAddress(), ethers.parseUnits("1000", 18));
      await dist.depositToken(await usdt.getAddress(), ethers.parseUnits("1000", 18));
    });

    it("payees returns all payees", async () => {
      const p = await dist.payees();
      expect(p).to.deep.equal([alice.address, bob.address]);
    });

    it("payeeAt works", async () => {
      expect(await dist.payeeAt(0)).to.equal(alice.address);
      expect(await dist.payeeAt(1)).to.equal(bob.address);
    });

    it("payeeAt reverts out of bounds", async () => {
      await expect(dist.payeeAt(99)).to.be.revertedWithCustomError(dist, "InvalidInput");
    });

    it("payeeCount works", async () => {
      expect(await dist.payeeCount()).to.equal(2);
    });

    it("trackedBalance reflects total minus claimed (native)", async () => {
      const total = ethers.parseEther("10");
      expect(await dist.trackedBalance(ZERO_ADDRESS)).to.equal(total);
      await dist.connect(alice).claimNative();
      const alicePart = (total * 7000n) / BPS;
      expect(await dist.trackedBalance(ZERO_ADDRESS)).to.equal(total - alicePart);
    });

    it("currentBalance matches actual contract balance (native)", async () => {
      const bal = await ethers.provider.getBalance(await dist.getAddress());
      expect(await dist.currentBalance(ZERO_ADDRESS)).to.equal(bal);
    });

    it("untrackedBalance is zero when all funds came via deposit", async () => {
      expect(await dist.untrackedBalance(ZERO_ADDRESS)).to.equal(0);
    });

    it("untrackedBalance reflects direct token transfers", async () => {
      const extra = ethers.parseUnits("77", 18);
      await usdt.mint(owner.address, extra);
      await usdt.transfer(await dist.getAddress(), extra);
      expect(await dist.untrackedBalance(await usdt.getAddress())).to.equal(extra);
    });
  });
});
