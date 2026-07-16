import type {
	ExtensionAPI,
	ExtensionContext,
} from "@earendil-works/pi-coding-agent";

import {
	DEFAULT_MERIDIAN_ENDPOINT,
	MeridianProfileCoordinator,
} from "./coordinator.ts";

function headerValue(
	headers: Record<string, string | null>,
	name: string,
): string | null {
	const entry = Object.entries(headers).find(
		([key]) => key.toLowerCase() === name.toLowerCase(),
	);
	return entry?.[1] ?? null;
}

function isMeridianRequest(headers: Record<string, string | null>): boolean {
	return headerValue(headers, "x-meridian-agent")?.toLowerCase() === "pi";
}

function setHeader(
	headers: Record<string, string | null>,
	name: string,
	value: string,
): void {
	const matchingKeys = Object.keys(headers).filter(
		(key) => key.toLowerCase() === name.toLowerCase(),
	);
	const targetKey = matchingKeys.shift() ?? name;
	for (const duplicateKey of matchingKeys) delete headers[duplicateKey];
	headers[targetKey] = value;
}

function deleteHeader(
	headers: Record<string, string | null>,
	name: string,
): void {
	for (const key of Object.keys(headers)) {
		if (key.toLowerCase() === name.toLowerCase()) delete headers[key];
	}
}

function describeError(error: unknown): string {
	return error instanceof Error ? error.message : String(error);
}

export default function meridianProfileAutoswitch(pi: ExtensionAPI): void {
	if (process.env.PI_MERIDIAN_AUTOSWITCH === "0") return;

	const coordinator = new MeridianProfileCoordinator({
		endpoint:
			process.env.PI_MERIDIAN_AUTOSWITCH_ENDPOINT ??
			process.env.PI_MERIDIAN_ENDPOINT ??
			DEFAULT_MERIDIAN_ENDPOINT,
		stateDirectory:
			process.env.PI_MERIDIAN_AUTOSWITCH_STATE_DIR || undefined,
	});
	// Pi's normal provider runtime is serialized, and after_provider_response
	// exposes neither request IDs nor request headers. Attribution therefore uses
	// the most recently routed profile. Overlapping provider requests remain a
	// residual risk; an invented queue would misattribute out-of-order responses.
	let lastRoutedProfile: string | undefined;
	let lastNotifiedError: string | undefined;
	let lastNotifiedAt = 0;
	const notifyError = (
		ctx: Pick<ExtensionContext, "hasUI" | "ui">,
		message: string,
	): void => {
		const now = Date.now();
		if (
			ctx.hasUI === false ||
			(message === lastNotifiedError && now - lastNotifiedAt < 60_000)
		) {
			return;
		}
		lastNotifiedError = message;
		lastNotifiedAt = now;
		ctx.ui.notify(message, "error");
	};

	pi.on("before_provider_headers", async (event, ctx) => {
		if (!isMeridianRequest(event.headers)) {
			lastRoutedProfile = undefined;
			return;
		}

		lastRoutedProfile = undefined;
		try {
			const profile = await coordinator.resolveProfile(ctx.model?.id ?? "");
			setHeader(event.headers, "x-meridian-profile", profile);
			lastRoutedProfile = profile;
			lastNotifiedError = undefined;
		} catch (error) {
			deleteHeader(event.headers, "x-meridian-profile");
			notifyError(
				ctx,
				`Meridian autoswitch could not select a profile: ${describeError(error)}`,
			);
		}
	});

	pi.on("after_provider_response", async (event, ctx) => {
		if (event.status !== 429 || !lastRoutedProfile) return;

		const failedProfile = lastRoutedProfile;
		try {
			await coordinator.quarantineProfile(failedProfile);
			// This hook runs after the response arrives, so it cannot retry the failed
			// request itself. The forced refresh affects the next provider request.
		} catch (error) {
			notifyError(
				ctx,
				`Meridian autoswitch could not quarantine ${failedProfile}: ${describeError(error)}`,
			);
		}
	});
}
