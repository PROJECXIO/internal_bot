frappe.ui.form.on("AI Provider Settings", {
	provider(frm) {
		apply_provider_defaults(frm);
	},

	refresh(frm) {
		frm.add_custom_button(__("Test Connection"), () => {
			test_connection(frm);
		}).addClass("btn-primary");

		frm.add_custom_button(__("Test Embeddings"), () => {
			test_embeddings(frm);
		});

		frm.add_custom_button(__("Quick Chat"), () => {
			open_quick_chat();
		});
	},
});

const DEFAULT_EMBEDDING_MODELS = {
	"OpenAI": "text-embedding-3-small",
	"Azure OpenAI": "text-embedding-3-small",
	"OpenRouter": "openai/text-embedding-3-small",
	"Anthropic": "",
};

function apply_provider_defaults(frm) {
	const current = frm.doc.embedding_model || "";
	if (current) return;

	const suggested = DEFAULT_EMBEDDING_MODELS[frm.doc.provider] || "";
	if (!suggested) return;

	frm.set_value("embedding_model", suggested);
}

// ── Test Connection ────────────────────────────────────────────────

function test_connection(frm) {
	const btn = frm.page.btn_primary;
	const original_label = btn.text();
	btn.text(__("Testing…")).prop("disabled", true);

	frappe.call({
		method: "internal_bot.internal_bot.doctype.ai_provider_settings.ai_provider_settings.test_connection",
		freeze: false,
		callback(r) {
			btn.text(original_label).prop("disabled", false);
			if (r.exc) return;
			const { success, message, model, latency_ms } = r.message;
			if (success) {
				frappe.show_alert(
					{ message: __("✓ Connected — {0} replied in {1} ms", [model, latency_ms]), indicator: "green" },
					6
				);
			} else {
				frappe.msgprint({
					title: __("Connection Failed"),
					indicator: "red",
					message: `<pre style="white-space:pre-wrap">${frappe.utils.escape_html(message)}</pre>`,
				});
			}
		},
		error() {
			btn.text(original_label).prop("disabled", false);
		},
	});
}

function test_embeddings(frm) {
	const button = frm.custom_buttons[__("Test Embeddings")];
	const original_label = button.text();
	button.text(__("Testing…")).prop("disabled", true);

	frappe.call({
		method: "internal_bot.internal_bot.doctype.ai_provider_settings.ai_provider_settings.test_embeddings",
		freeze: false,
		callback(r) {
			button.text(original_label).prop("disabled", false);
			if (r.exc) return;
			const { success, message, embedding_model, latency_ms, dimensions } = r.message;
			if (success) {
				frappe.show_alert(
					{
						message: __("✓ Embeddings OK — {0} ({1} dims) in {2} ms", [
							embedding_model,
							dimensions,
							latency_ms,
						]),
						indicator: "green",
					},
					6
				);
			} else {
				frappe.msgprint({
					title: __("Embeddings Test Failed"),
					indicator: "red",
					message: `<pre style="white-space:pre-wrap">${frappe.utils.escape_html(message)}</pre>`,
				});
			}
		},
		error() {
			button.text(original_label).prop("disabled", false);
		},
	});
}

// ── Quick Chat dialog ──────────────────────────────────────────────

function open_quick_chat() {
	const d = new frappe.ui.Dialog({
		title: __("Quick Chat"),
		size: "large",
	});

	// Build dialog body manually for full layout control
	$(d.body).html(`
		<div style="display:flex; flex-direction:column; gap:12px;">
			<textarea id="qc-input"
				rows="3"
				class="form-control"
				placeholder="${__("Type a message…")}"
				style="resize:vertical; font-size:14px;"
			>Hi, how are you?</textarea>

			<button id="qc-ask" class="btn btn-primary btn-sm" style="align-self:flex-start; min-width:80px;">
				${__("Ask")}
			</button>

			<div id="qc-response-wrap" style="display:none; border:1px solid var(--border-color); border-radius:6px; overflow:hidden;">
				<div style="background:var(--subtle-fg); padding:8px 12px; display:flex; justify-content:space-between; align-items:center;">
					<span style="font-weight:600; font-size:12px; text-transform:uppercase; letter-spacing:.5px; color:var(--text-muted);">
						${__("Response")}
					</span>
					<span id="qc-tokens" style="font-size:12px; color:var(--text-muted);"></span>
				</div>
				<div id="qc-response"
					style="padding:12px 14px; white-space:pre-wrap; font-size:14px; line-height:1.6; min-height:60px; max-height:320px; overflow-y:auto; background:var(--card-bg);">
				</div>
			</div>
		</div>
	`);

	const $input    = $(d.body).find("#qc-input");
	const $ask      = $(d.body).find("#qc-ask");
	const $wrap     = $(d.body).find("#qc-response-wrap");
	const $response = $(d.body).find("#qc-response");
	const $tokens   = $(d.body).find("#qc-tokens");

	function ask() {
		const message = $input.val().trim();
		if (!message) return;

		$ask.text(__("Asking…")).prop("disabled", true);
		$wrap.hide();

		frappe.call({
			method: "internal_bot.internal_bot.doctype.ai_provider_settings.ai_provider_settings.quick_chat",
			args: { message },
			freeze: false,
			callback(r) {
				$ask.text(__("Ask")).prop("disabled", false);
				if (r.exc) return;

				const { success, reply, error, input_tokens, output_tokens, model } = r.message;

				if (success) {
					$response.text(reply);
					$tokens.text(__("{0} | in {1} / out {2} tokens", [model, input_tokens, output_tokens]));
				} else {
					$response
						.css("color", "var(--red)")
						.text(error);
					$tokens.text("");
				}
				$wrap.show();
			},
			error() {
				$ask.text(__("Ask")).prop("disabled", false);
			},
		});
	}

	// Ask on button click or Ctrl+Enter in textarea
	$ask.on("click", ask);
	$input.on("keydown", (e) => {
		if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) ask();
	});

	d.show();
	// Focus the textarea after dialog opens
	setTimeout(() => $input.focus().select(), 150);
}
