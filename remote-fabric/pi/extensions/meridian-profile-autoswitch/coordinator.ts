import { randomUUID } from "node:crypto";
import {
	lstat,
	mkdir,
	readdir,
	readFile,
	readlink,
	rename,
	rm,
	stat,
	symlink,
	writeFile,
} from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";

import {
	decideProfile,
	fiveHourResetAt,
	type LeaseState,
	type MeridianProfileMetadata,
	type MeridianQuotaProfile,
} from "./policy.ts";

export const DEFAULT_MERIDIAN_ENDPOINT = `http://${"127.0.0.1"}:${3456}`;
const DEFAULT_CHECK_TTL_MS = 10_000;
const DEFAULT_REQUEST_TIMEOUT_MS = 2_500;
const DEFAULT_MAX_QUOTA_AGE_MS = 90_000;
const DEFAULT_FALLBACK_QUARANTINE_MS = 5 * 60_000;
const DEFAULT_API_FAILURE_MAX_LEASE_AGE_MS = 5 * 60_000;
const DEFAULT_THRESHOLD = 0.98;
const DEFAULT_LOCK_STALE_MS = 15_000;
const DEFAULT_LOCK_WAIT_MS = 20_000;
const DEFAULT_LOCK_RETRY_MS = 25;
const LEGACY_FENCE_OWNER = "1:generation-protocol";

export interface CoordinatorOptions {
	endpoint?: string;
	stateDirectory?: string;
	now?: () => number;
	checkTtlMs?: number;
	requestTimeoutMs?: number;
	maxQuotaAgeMs?: number;
	fallbackQuarantineMs?: number;
	apiFailureMaxLeaseAgeMs?: number;
	threshold?: number;
	lockStaleMs?: number;
	lockWaitMs?: number;
	lockRetryMs?: number;
	isProcessAlive?: (pid: number) => boolean;
	testHooks?: {
		beforeGenerationPublish?: (generation: number) => void | Promise<void>;
	};
}

interface ProfileListResponse {
	profiles: MeridianProfileMetadata[];
	activeProfile: string | null;
}

interface QuotaResponse {
	profiles: MeridianQuotaProfile[];
	activeProfile: string | null;
	asOf: number | string | null;
}

function initialState(): LeaseState {
	return {
		selectedProfile: null,
		selectedAt: 0,
		lastCheckedAt: 0,
		lastObservedMeridianActive: null,
		quarantinedUntil: {},
		fiveHourResetsAt: {},
	};
}

function errorCode(error: unknown): string | undefined {
	if (!error || typeof error !== "object" || !("code" in error))
		return undefined;
	return typeof error.code === "string" ? error.code : undefined;
}

function numericRecord(value: unknown): Record<string, number> {
	if (!value || typeof value !== "object" || Array.isArray(value)) return {};
	return Object.fromEntries(
		Object.entries(value).filter(
			(entry): entry is [string, number] =>
				typeof entry[1] === "number" && Number.isFinite(entry[1]),
		),
	);
}

function normalizeState(value: unknown): LeaseState {
	if (!value || typeof value !== "object" || Array.isArray(value)) {
		return initialState();
	}
	const state = value as Partial<LeaseState>;
	return {
		selectedProfile:
			typeof state.selectedProfile === "string" ? state.selectedProfile : null,
		selectedAt:
			typeof state.selectedAt === "number" && Number.isFinite(state.selectedAt)
				? state.selectedAt
				: 0,
		lastCheckedAt:
			typeof state.lastCheckedAt === "number" &&
			Number.isFinite(state.lastCheckedAt)
				? state.lastCheckedAt
				: 0,
		lastObservedMeridianActive:
			typeof state.lastObservedMeridianActive === "string"
				? state.lastObservedMeridianActive
				: null,
		quarantinedUntil: numericRecord(state.quarantinedUntil),
		fiveHourResetsAt: numericRecord(state.fiveHourResetsAt),
		lastCheckedModelId:
			typeof state.lastCheckedModelId === "string"
				? state.lastCheckedModelId
				: undefined,
		forceRefresh: state.forceRefresh === true,
	};
}

function delay(milliseconds: number): Promise<void> {
	return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

interface GenerationLockOwner {
	token: string;
	pid: number;
	createdAt: number;
}

interface AcquiredGenerationLock {
	path: string;
	owner: GenerationLockOwner;
}

function processIsAlive(pid: number): boolean {
	if (!Number.isInteger(pid) || pid <= 0) return false;
	try {
		process.kill(pid, 0);
		return true;
	} catch (error) {
		return errorCode(error) !== "ESRCH";
	}
}

export class MeridianProfileCoordinator {
	private readonly endpoint: string;
	private readonly stateDirectory: string;
	private readonly statePath: string;
	private readonly now: () => number;
	private readonly checkTtlMs: number;
	private readonly requestTimeoutMs: number;
	private readonly maxQuotaAgeMs: number;
	private readonly fallbackQuarantineMs: number;
	private readonly apiFailureMaxLeaseAgeMs: number;
	private readonly threshold: number;
	private readonly lockStaleMs: number;
	private readonly lockWaitMs: number;
	private readonly lockRetryMs: number;
	private readonly isProcessAlive: (pid: number) => boolean;
	private readonly beforeGenerationPublish?: (
		generation: number,
	) => void | Promise<void>;

	constructor(options: CoordinatorOptions = {}) {
		this.endpoint = (options.endpoint ?? DEFAULT_MERIDIAN_ENDPOINT).replace(
			/\/$/,
			"",
		);
		this.stateDirectory =
			options.stateDirectory ??
			join(homedir(), ".cache", "pi-meridian-autoswitch");
		this.statePath = join(this.stateDirectory, "state.json");
		this.now = options.now ?? Date.now;
		this.checkTtlMs = options.checkTtlMs ?? DEFAULT_CHECK_TTL_MS;
		this.requestTimeoutMs =
			options.requestTimeoutMs ?? DEFAULT_REQUEST_TIMEOUT_MS;
		this.maxQuotaAgeMs = options.maxQuotaAgeMs ?? DEFAULT_MAX_QUOTA_AGE_MS;
		this.fallbackQuarantineMs =
			options.fallbackQuarantineMs ?? DEFAULT_FALLBACK_QUARANTINE_MS;
		this.apiFailureMaxLeaseAgeMs =
			options.apiFailureMaxLeaseAgeMs ?? DEFAULT_API_FAILURE_MAX_LEASE_AGE_MS;
		this.threshold = options.threshold ?? DEFAULT_THRESHOLD;
		this.lockStaleMs = options.lockStaleMs ?? DEFAULT_LOCK_STALE_MS;
		this.lockRetryMs = options.lockRetryMs ?? DEFAULT_LOCK_RETRY_MS;
		this.lockWaitMs = Math.max(
			options.lockWaitMs ?? DEFAULT_LOCK_WAIT_MS,
			this.lockStaleMs + this.lockRetryMs,
		);
		this.isProcessAlive = options.isProcessAlive ?? processIsAlive;
		this.beforeGenerationPublish = options.testHooks?.beforeGenerationPublish;
	}

	async resolveProfile(modelId: string): Promise<string> {
		const state = await this.readState();
		if (state.selectedProfile && this.isFreshUsableLease(state, modelId)) {
			return state.selectedProfile;
		}

		return this.withLock(async () => {
			const current = await this.readState();
			if (
				current.selectedProfile &&
				this.isFreshUsableLease(current, modelId)
			) {
				return current.selectedProfile;
			}

			let list: ProfileListResponse;
			let quota: QuotaResponse;
			try {
				[list, quota] = await Promise.all([
					this.getProfileList(),
					this.getQuota(),
				]);
			} catch (error) {
				const now = this.now();
				const leaseAge = now - current.lastCheckedAt;
				if (
					current.selectedProfile &&
					!current.forceRefresh &&
					(current.quarantinedUntil[current.selectedProfile] ?? 0) <= now &&
					leaseAge >= 0 &&
					leaseAge <= this.apiFailureMaxLeaseAgeMs
				) {
					return current.selectedProfile;
				}
				throw error;
			}

			const now = this.now();
			const activeProfile = list.activeProfile ?? quota.activeProfile;
			const decision = decideProfile({
				profiles: list.profiles,
				quotaProfiles: quota.profiles,
				activeProfile,
				quotaAsOf: quota.asOf,
				state: current,
				now,
				threshold: this.threshold,
				maxQuotaAgeMs: this.maxQuotaAgeMs,
				modelId,
			});

			const selectedChanged = decision.profile !== current.selectedProfile;
			const fiveHourResetsAt = Object.fromEntries(
				quota.profiles.flatMap((profile) => {
					const reset = fiveHourResetAt(profile);
					return reset === null ? [] : [[profile.id, reset]];
				}),
			);
			const quarantinedUntil = Object.fromEntries(
				Object.entries(current.quarantinedUntil).filter(
					([, until]) => until > now,
				),
			);
			const observedActiveWasAccepted =
				decision.reason !== "stale-quota" &&
				decision.profile !== null &&
				activeProfile === decision.profile;
			const next: LeaseState = {
				...current,
				selectedProfile: decision.profile,
				selectedAt: selectedChanged ? now : current.selectedAt,
				lastCheckedAt: now,
				lastCheckedModelId: modelId,
				lastObservedMeridianActive: observedActiveWasAccepted
					? activeProfile
					: current.lastObservedMeridianActive,
				quarantinedUntil,
				fiveHourResetsAt,
				forceRefresh: false,
			};
			await this.writeState(next);

			if (!decision.profile) {
				throw new Error("Meridian returned no profile eligible for routing");
			}
			return decision.profile;
		});
	}

	async quarantineProfile(profile: string): Promise<void> {
		await this.withLock(async () => {
			const state = await this.readState();
			const now = this.now();
			const knownReset = state.fiveHourResetsAt[profile];
			const until =
				typeof knownReset === "number" && knownReset > now
					? knownReset
					: now + this.fallbackQuarantineMs;
			await this.writeState({
				...state,
				lastCheckedAt: 0,
				quarantinedUntil: {
					...state.quarantinedUntil,
					[profile]: until,
				},
				forceRefresh: true,
			});
		});
	}

	private isFreshUsableLease(state: LeaseState, modelId: string): boolean {
		if (!state.selectedProfile || state.forceRefresh) return false;
		if (state.lastCheckedModelId && state.lastCheckedModelId !== modelId) {
			return false;
		}
		const now = this.now();
		if ((state.quarantinedUntil[state.selectedProfile] ?? 0) > now)
			return false;
		const age = now - state.lastCheckedAt;
		return age >= 0 && age < this.checkTtlMs;
	}

	private async getProfileList(): Promise<ProfileListResponse> {
		const value = await this.getJson("/profiles/list");
		if (!value || typeof value !== "object" || Array.isArray(value)) {
			throw new Error("Invalid response from Meridian /profiles/list");
		}
		const response = value as Partial<ProfileListResponse>;
		if (!Array.isArray(response.profiles)) {
			throw new Error("Meridian /profiles/list omitted profiles");
		}
		return {
			profiles: response.profiles.filter(
				(profile): profile is MeridianProfileMetadata =>
					Boolean(profile) && typeof profile.id === "string",
			),
			activeProfile:
				typeof response.activeProfile === "string"
					? response.activeProfile
					: null,
		};
	}

	private async getQuota(): Promise<QuotaResponse> {
		const value = await this.getJson("/v1/usage/quota/all");
		if (!value || typeof value !== "object" || Array.isArray(value)) {
			throw new Error("Invalid response from Meridian /v1/usage/quota/all");
		}
		const response = value as Partial<QuotaResponse>;
		if (!Array.isArray(response.profiles)) {
			throw new Error("Meridian quota response omitted profiles");
		}
		return {
			profiles: response.profiles.filter(
				(profile): profile is MeridianQuotaProfile =>
					Boolean(profile) && typeof profile.id === "string",
			),
			activeProfile:
				typeof response.activeProfile === "string"
					? response.activeProfile
					: null,
			asOf: response.asOf ?? null,
		};
	}

	private async getJson(path: string): Promise<unknown> {
		const signal = AbortSignal.timeout(this.requestTimeoutMs);
		const response = await fetch(`${this.endpoint}${path}`, {
			method: "GET",
			headers: { accept: "application/json" },
			signal,
		});
		if (!response.ok) {
			throw new Error(`Meridian ${path} returned HTTP ${response.status}`);
		}
		return response.json();
	}

	private async readState(): Promise<LeaseState> {
		try {
			return normalizeState(JSON.parse(await readFile(this.statePath, "utf8")));
		} catch (error) {
			if (errorCode(error) === "ENOENT") return initialState();
			throw error;
		}
	}

	private async writeState(state: LeaseState): Promise<void> {
		await mkdir(this.stateDirectory, { recursive: true });
		const temporaryPath = join(
			this.stateDirectory,
			`.state.${process.pid}.${randomUUID()}.tmp`,
		);
		try {
			await writeFile(
				temporaryPath,
				`${JSON.stringify(state, null, 2)}\n`,
				"utf8",
			);
			await rename(temporaryPath, this.statePath);
		} finally {
			await rm(temporaryPath, { force: true });
		}
	}

	private async withLock<T>(operation: () => Promise<T>): Promise<T> {
		await mkdir(this.stateDirectory, { recursive: true });
		const acquired = await this.waitForGenerationLock(Date.now());

		try {
			return await operation();
		} finally {
			await this.releaseGenerationLock(acquired);
		}
	}

	private async waitForGenerationLock(
		startedWaitingAt: number,
	): Promise<AcquiredGenerationLock> {
		const acquired = await this.tryAcquireGenerationLock();
		if (acquired) return acquired;
		if (Date.now() - startedWaitingAt >= this.lockWaitMs) {
			throw new Error("Timed out waiting for Meridian autoswitch state lock");
		}
		await delay(this.lockRetryMs);
		return this.waitForGenerationLock(startedWaitingAt);
	}

	/**
	 * Generations are never reused. Owner metadata is the symlink target, so
	 * publication and exclusive creation are one atomic filesystem operation.
	 * Older records are retired only after a higher generation exists.
	 */
	private async tryAcquireGenerationLock(): Promise<AcquiredGenerationLock | null> {
		if (await this.legacyLockBlocksAcquisition()) return null;

		const entries = await readdir(this.stateDirectory, { withFileTypes: true });
		const generations = entries.flatMap((entry) => {
			const match = /^\.lock-(\d+)$/.exec(entry.name);
			return match && (entry.isSymbolicLink() || entry.isDirectory())
				? [Number(match[1])]
				: [];
		});
		for (const generation of generations) {
			if (
				await this.generationLockBlocksAcquisition(
					join(this.stateDirectory, `.lock-${generation}`),
				)
			) {
				return null;
			}
		}

		const generation =
			generations.length === 0 ? 0 : Math.max(...generations) + 1;
		await this.beforeGenerationPublish?.(generation);
		const path = join(this.stateDirectory, `.lock-${generation}`);
		const owner: GenerationLockOwner = {
			token: randomUUID(),
			pid: process.pid,
			createdAt: Date.now(),
		};
		try {
			await symlink(JSON.stringify(owner), path);
		} catch (error) {
			if (errorCode(error) === "EEXIST") return null;
			throw error;
		}

		const acquired = { path, owner };
		if (await this.hasHigherGeneration(generation)) {
			await this.releaseGenerationLock(acquired);
			return null;
		}
		const publishedOwner = await this.readGenerationOwner(path);
		if (!publishedOwner || publishedOwner.token !== owner.token) return null;

		await this.cleanupOlderGenerations(generations, generation).catch(
			() => undefined,
		);
		return acquired;
	}

	private async hasHigherGeneration(generation: number): Promise<boolean> {
		const entries = await readdir(this.stateDirectory, { withFileTypes: true });
		return entries.some((entry) => {
			const match = /^\.lock-(\d+)$/.exec(entry.name);
			return (
				match !== null &&
				(entry.isSymbolicLink() || entry.isDirectory()) &&
				Number(match[1]) > generation
			);
		});
	}

	private async generationLockBlocksAcquisition(
		path: string,
	): Promise<boolean> {
		try {
			const [owner, metadata, releasedBy] = await Promise.all([
				this.readGenerationOwner(path),
				lstat(path),
				this.readGenerationRelease(path),
			]);
			if (owner && releasedBy === owner.token) return false;
			if (owner && this.isProcessAlive(owner.pid)) return true;
			const createdAt = owner?.createdAt ?? metadata.mtimeMs;
			const age = Date.now() - createdAt;
			return age < 0 || age <= this.lockStaleMs;
		} catch (error) {
			if (errorCode(error) === "ENOENT") return false;
			throw error;
		}
	}

	private async cleanupOlderGenerations(
		generations: number[],
		currentGeneration: number,
	): Promise<void> {
		await Promise.all(
			generations
				.filter((generation) => generation < currentGeneration)
				.map(async (generation) => {
					const path = join(this.stateDirectory, `.lock-${generation}`);
					if (await this.generationLockBlocksAcquisition(path)) {
						return undefined;
					}
					await rm(path, { recursive: true, force: true });
					return rm(`${path}.released`, { force: true });
				}),
		);
	}

	private async releaseGenerationLock(
		lock: AcquiredGenerationLock,
	): Promise<void> {
		const owner = await this.readGenerationOwner(lock.path);
		if (!owner || owner.token !== lock.owner.token) return;
		try {
			await writeFile(`${lock.path}.released`, lock.owner.token, {
				encoding: "utf8",
				flag: "wx",
			});
		} catch (error) {
			if (errorCode(error) !== "EEXIST") throw error;
		}
	}

	private async readGenerationOwner(
		path: string,
	): Promise<GenerationLockOwner | null> {
		let serialized: string;
		try {
			serialized = await readlink(path);
		} catch (error) {
			if (errorCode(error) === "ENOENT") return null;
			if (errorCode(error) !== "EINVAL") throw error;
			// Read the directory format used before atomic symlink publication.
			try {
				serialized = await readFile(join(path, "owner.json"), "utf8");
			} catch (legacyError) {
				if (errorCode(legacyError) === "ENOENT") return null;
				throw legacyError;
			}
		}
		try {
			const value = JSON.parse(serialized) as Partial<GenerationLockOwner>;
			if (
				typeof value.token === "string" &&
				typeof value.pid === "number" &&
				typeof value.createdAt === "number"
			) {
				return value as GenerationLockOwner;
			}
		} catch (error) {
			if (!(error instanceof SyntaxError)) throw error;
		}
		return null;
	}

	private async readGenerationRelease(path: string): Promise<string | null> {
		try {
			return await readFile(`${path}.released`, "utf8");
		} catch (error) {
			if (errorCode(error) !== "ENOENT") throw error;
			// Support released directory-generation records from the prior protocol.
			try {
				return await readFile(join(path, "released"), "utf8");
			} catch (legacyError) {
				if (
					errorCode(legacyError) === "ENOENT" ||
					errorCode(legacyError) === "ENOTDIR"
				) {
					return null;
				}
				throw legacyError;
			}
		}
	}

	private async legacyLockBlocksAcquisition(): Promise<boolean> {
		const legacyPath = join(this.stateDirectory, "lock");
		while (true) {
			let metadata;
			try {
				metadata = await stat(legacyPath);
			} catch (error) {
				if (errorCode(error) !== "ENOENT") throw error;
				try {
					await mkdir(legacyPath);
					await writeFile(join(legacyPath, "owner"), LEGACY_FENCE_OWNER, {
						encoding: "utf8",
						flag: "wx",
					});
					return false;
				} catch (acquireError) {
					if (errorCode(acquireError) === "EEXIST") continue;
					throw acquireError;
				}
			}

			let owner: string | null = null;
			try {
				owner = await readFile(join(legacyPath, "owner"), "utf8");
			} catch (error) {
				if (errorCode(error) !== "ENOENT") throw error;
			}
			if (owner === LEGACY_FENCE_OWNER) return false;

			const parsedPid = Number(owner?.split(":", 1)[0]);
			if (
				Number.isInteger(parsedPid) &&
				parsedPid > 0 &&
				this.isProcessAlive(parsedPid)
			) {
				return true;
			}
			if (Date.now() - metadata.mtimeMs <= this.lockStaleMs) return true;

			// A fixed-path lock cannot be retired with compare-and-swap semantics.
			// Automatic migration would let concurrent stale observers move a new
			// owner. Fail safely and require one-time cleanup instead.
			throw new Error(
				`Stale legacy Meridian autoswitch lock at ${legacyPath}; remove it after confirming no older Pi session is using it`,
			);
		}
	}
}
