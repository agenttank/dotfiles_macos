export interface MeridianProfileMetadata {
	id: string;
	type?: string;
	loggedIn?: boolean;
}

export interface MeridianQuotaWindow {
	type: string;
	utilization: number | null;
	resetsAt?: number | string | null;
}

export interface MeridianQuotaProfile {
	id: string;
	error?: unknown;
	windows?: MeridianQuotaWindow[];
}

export interface LeaseState {
	selectedProfile: string | null;
	selectedAt: number;
	lastCheckedAt: number;
	lastObservedMeridianActive: string | null;
	quarantinedUntil: Record<string, number>;
	fiveHourResetsAt: Record<string, number>;
	lastCheckedModelId?: string;
	forceRefresh?: boolean;
}

export interface SelectionInput {
	profiles: MeridianProfileMetadata[];
	quotaProfiles: MeridianQuotaProfile[];
	activeProfile: string | null;
	quotaAsOf: number | string | null;
	state: LeaseState;
	now: number;
	threshold: number;
	maxQuotaAgeMs: number;
	modelId: string;
}

export type SelectionReason =
	| "lease-kept"
	| "manual-active"
	| "quota-switch"
	| "all-quota-exhausted"
	| "no-eligible-profile"
	| "stale-quota";

export interface ProfileDecision {
	profile: string | null;
	reason: SelectionReason;
}

interface Candidate {
	id: string;
	fiveHour: number;
	weekly: number;
	quotaKnown: boolean;
}

type ProfileAssessment =
	| { kind: "eligible"; candidate: Candidate }
	| { kind: "quota-exhausted" }
	| { kind: "unsafe" };

function timestamp(value: number | string | null | undefined): number | null {
	if (typeof value === "number" && Number.isFinite(value)) return value;
	if (typeof value !== "string") return null;
	const parsed = Date.parse(value);
	return Number.isFinite(parsed) ? parsed : null;
}

function utilization(window: MeridianQuotaWindow | undefined): number | null {
	const value = window?.utilization;
	return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function modelSpecificWeeklyWindows(
	windows: MeridianQuotaWindow[],
	modelId: string,
): MeridianQuotaWindow[] {
	const normalizedModel = modelId.toLowerCase().replaceAll("_", "-");
	return windows.filter((window) => {
		if (!window.type.startsWith("seven_day_")) return false;
		const modelFamily = window.type
			.slice("seven_day_".length)
			.replaceAll("_", "-");
		return modelFamily.length > 0 && normalizedModel.includes(modelFamily);
	});
}

function assessProfile(
	id: string,
	input: SelectionInput,
	profilesById: Map<string, MeridianProfileMetadata>,
	quotaById: Map<string, MeridianQuotaProfile>,
): ProfileAssessment {
	const metadata = profilesById.get(id);
	const quota = quotaById.get(id);
	if (
		!metadata ||
		metadata.loggedIn !== true ||
		!quota ||
		(input.state.quarantinedUntil[id] ?? 0) > input.now
	) {
		return { kind: "unsafe" };
	}

	// Meridian 1.45 can report a profile as authenticated/routable while its
	// usage endpoint returns `no_token` (notably for inactive profiles). Keep
	// those profiles as last-resort routing candidates: a real quota snapshot is
	// always preferred, and a 429 will quarantine and rotate this fallback.
	if (quota.error === "no_token") {
		return {
			kind: "eligible",
			candidate: {
				id,
				fiveHour: Number.POSITIVE_INFINITY,
				weekly: Number.POSITIVE_INFINITY,
				quotaKnown: false,
			},
		};
	}
	if (quota.error !== null && quota.error !== undefined) {
		return { kind: "unsafe" };
	}

	const windows = Array.isArray(quota.windows) ? quota.windows : [];
	const fiveHour = utilization(
		windows.find((window) => window.type === "five_hour"),
	);
	const generalWeekly = utilization(
		windows.find((window) => window.type === "seven_day"),
	);
	if (fiveHour === null || generalWeekly === null) return { kind: "unsafe" };

	const specificWeekly = modelSpecificWeeklyWindows(windows, input.modelId).map(
		(window) => utilization(window),
	);
	if (specificWeekly.some((value) => value === null)) {
		return { kind: "unsafe" };
	}

	const weekly = Math.max(generalWeekly, ...(specificWeekly as number[]));
	if (fiveHour >= input.threshold || weekly >= input.threshold) {
		return { kind: "quota-exhausted" };
	}

	return {
		kind: "eligible",
		candidate: { id, fiveHour, weekly, quotaKnown: true },
	};
}

function isQuotaStale(input: SelectionInput): boolean {
	const asOf = timestamp(input.quotaAsOf);
	return asOf === null || input.now - asOf > input.maxQuotaAgeMs;
}

/**
 * Choose the profile header for the next request without changing Meridian's
 * global active profile. Existing healthy leases are intentionally sticky.
 */
export function decideProfile(input: SelectionInput): ProfileDecision {
	const current = input.state.selectedProfile;
	const profilesById = new Map(
		input.profiles.map((profile) => [profile.id, profile]),
	);
	const quotaById = new Map(
		input.quotaProfiles.map((profile) => [profile.id, profile]),
	);
	const assessment = (id: string | null): ProfileAssessment =>
		id
			? assessProfile(id, input, profilesById, quotaById)
			: { kind: "unsafe" };
	const eligible = (id: string | null): Candidate | null => {
		const result = assessment(id);
		return result.kind === "eligible" ? result.candidate : null;
	};

	if (isQuotaStale(input)) {
		return {
			profile: assessment(current).kind === "unsafe" ? null : current,
			reason: "stale-quota",
		};
	}

	const activeChanged =
		input.activeProfile !== null &&
		input.activeProfile !== input.state.lastObservedMeridianActive;
	if (activeChanged && eligible(input.activeProfile)) {
		return { profile: input.activeProfile, reason: "manual-active" };
	}

	if (eligible(current)) return { profile: current, reason: "lease-kept" };

	const assessments = input.profiles.map((profile) => ({
		id: profile.id,
		assessment: assessment(profile.id),
	}));
	const candidates = assessments
		.flatMap(({ assessment }) =>
			assessment.kind === "eligible" ? [assessment.candidate] : [],
		)
		.sort(
			(left, right) =>
				Number(right.quotaKnown) - Number(left.quotaKnown) ||
				left.fiveHour - right.fiveHour ||
				left.weekly - right.weekly ||
				left.id.localeCompare(right.id),
		);

	if (candidates.length > 0) {
		return { profile: candidates[0].id, reason: "quota-switch" };
	}

	// Only profiles whose identity, login, quota payload, and reset state are
	// all known-safe may deliberately surface Meridian's normal quota-limit path.
	const allKnownProfilesAreQuotaExhausted =
		assessments.length > 0 &&
		assessments.every(
			({ assessment }) => assessment.kind === "quota-exhausted",
		);
	if (allKnownProfilesAreQuotaExhausted) {
		const exhaustedProfile = [current, input.activeProfile]
			.filter((id): id is string => id !== null)
			.find((id) => assessment(id).kind === "quota-exhausted");
		return {
			profile: exhaustedProfile ?? assessments[0].id,
			reason: "all-quota-exhausted",
		};
	}

	return { profile: null, reason: "no-eligible-profile" };
}

export function fiveHourResetAt(profile: MeridianQuotaProfile): number | null {
	const windows = Array.isArray(profile.windows) ? profile.windows : [];
	return timestamp(
		windows.find((window) => window.type === "five_hour")?.resetsAt,
	);
}
