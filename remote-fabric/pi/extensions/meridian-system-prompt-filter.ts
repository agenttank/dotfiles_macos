const BAD_PI_DOC_GUIDANCE = [
	/^- When reading pi docs or examples,/,
	/^- When asked about: extensions /,
	/^- When working on pi topics,/,
	/^- Always read pi \.md files /,
];

function stripBadGuidance(text: string): string {
	return text
		.split("\n")
		.filter(
			(line) => !BAD_PI_DOC_GUIDANCE.some((pattern) => pattern.test(line)),
		)
		.join("\n");
}

function stripSystem(system: unknown): unknown {
	if (typeof system === "string") return stripBadGuidance(system);
	if (!Array.isArray(system)) return system;

	return system.map((block) => {
		if (!block || typeof block !== "object") return block;
		const maybeTextBlock = block as { type?: unknown; text?: unknown };
		if (maybeTextBlock.type !== "text" || typeof maybeTextBlock.text !== "string") {
			return block;
		}

		const nextText = stripBadGuidance(maybeTextBlock.text);
		return nextText === maybeTextBlock.text ? block : { ...block, text: nextText };
	});
}

export default function meridianSystemPromptFilter(pi: {
	on: (
		eventName: "before_provider_request",
		handler: (event: { payload: unknown }) => unknown,
	) => void;
}): void {
	pi.on("before_provider_request", (event) => {
		const payload = event.payload;
		if (!payload || typeof payload !== "object") return;

		const maybePayload = payload as { system?: unknown };
		if (!("system" in maybePayload)) return;

		const nextSystem = stripSystem(maybePayload.system);
		if (nextSystem === maybePayload.system) return;

		return { ...maybePayload, system: nextSystem };
	});
}
