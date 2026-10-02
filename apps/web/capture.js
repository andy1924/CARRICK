/* Browser microphone capture; local server OCR and speech; editable source previews. */
window.CarrickCapture = (() => {
  let app, recorder, stream, chunks = [], timer, objectUrl, voiceDraft, documentDraft, voiceSource;
  const $ = selector => document.querySelector(selector);
  const safe = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const blobBase64 = blob => new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1]);
    reader.onerror = () => reject(new Error("The file could not be read"));
    reader.readAsDataURL(blob);
  });
  const metadata = () => ({ event_date: $("#report-date").value, discipline: $("#report-discipline").value, location: $("#report-location").value });
  const notify = () => window.dispatchEvent(new Event("carrick-drafts-changed"));

  function showVoice(draft) {
    voiceDraft = draft;
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = URL.createObjectURL(draft.blob);
    $("#voice-audio").src = objectUrl;
    $("#voice-preview").hidden = false;
    $("#voice-transcribe").disabled = false;
    $("#voice-text").value = draft.receipt?.text || "";
    $("#voice-transcript").hidden = !draft.receipt;
    $("#voice-status").textContent = draft.receipt ? "Transcript ready. Check the wording before using it." : "Recording saved on this device. Transcribe when the local server is available.";
  }

  async function toggleRecording() {
    if (recorder?.state === "recording") { $("#voice-record").disabled = true; recorder.stop(); return; }
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder || !window.isSecureContext) {
      return app.toast("Microphone capture needs a supported browser on HTTPS or localhost.", true);
    }
    $("#voice-record").disabled = true;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mime = ["audio/webm;codecs=opus", "audio/mp4", "audio/ogg;codecs=opus"].find(value => MediaRecorder.isTypeSupported(value));
      recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : {});
      chunks = [];
      recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
      recorder.onstop = async () => {
        clearTimeout(timer);
        stream.getTracks().forEach(track => track.stop());
        $("#voice-record").textContent = "Record voice note";
        $("#voice-record").setAttribute("aria-pressed", "false");
        try {
          const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
          if (!blob.size || blob.size > 10000000) throw new Error("Recording must be non-empty and under 10 MB.");
          const suffix = blob.type.includes("mp4") ? "mp4" : blob.type.includes("ogg") ? "ogg" : "webm";
          const draft = { id: app.offline.id(), kind: "voice", blob, filename: `voice-note.${suffix}`, savedAt: new Date().toISOString(), scheduleVersion: app.getSchedule(), ...metadata() };
          await app.offline.put("drafts", draft);
          showVoice(draft); notify();
        } catch (error) { app.toast(error.message, true); }
        finally { $("#voice-record").disabled = false; }
      };
      recorder.onerror = () => { clearTimeout(timer); stream.getTracks().forEach(track => track.stop()); app.toast("Recording was interrupted. Try again.", true); };
      recorder.start(1000);
      timer = setTimeout(() => { if (recorder.state === "recording") { $("#voice-record").disabled = true; recorder.stop(); } }, 120000);
      $("#voice-record").textContent = "Stop recording";
      $("#voice-record").setAttribute("aria-pressed", "true");
      $("#voice-status").textContent = "Recording… microphone stops after two minutes.";
    } catch (error) {
      stream?.getTracks().forEach(track => track.stop());
      app.toast(error.name === "NotAllowedError" ? "Microphone permission was declined. You can still type a report." : "The microphone could not be opened.", true);
    } finally { $("#voice-record").disabled = false; }
  }

  async function transcribe() {
    if (!voiceDraft) return;
    if (!app.offline.reachable) return app.toast("Recording is saved. Reconnect to the local server before transcribing.");
    const button = $("#voice-transcribe");
    button.disabled = true; button.textContent = "Transcribing…";
    try {
      const receipt = await app.post("/api/voice/transcribe", { filename: voiceDraft.filename, content: await blobBase64(voiceDraft.blob), language: $("#voice-language").value });
      voiceDraft.receipt = receipt;
      await app.offline.put("drafts", voiceDraft);
      showVoice(voiceDraft); notify();
    } catch (error) { app.toast(error.message, true); }
    finally { button.disabled = false; button.textContent = "Transcribe locally"; }
  }

  function showDocument(draft) {
    documentDraft = draft;
    const receipt = draft.receipt;
    $("#document-review").hidden = false;
    $("#document-review-title").textContent = `Review ${receipt.filename}`;
    $("#document-original").href = receipt.original_url;
    $("#document-pages").innerHTML = receipt.pages.map((page, index) => `<div class="extracted-page"><div class="page-source"><strong>${page.source_row ? `Page ${page.source_row}` : "Source text"}</strong><span>${safe(({ tesseract: "Printed text OCR", local_vision: "Handwriting transcription", text_layer: "PDF text layer", text: "Original text" })[page.method] || page.method)}${page.confidence != null ? ` · OCR confidence ${page.confidence}%` : ""}</span></div>${page.warnings.map(warning => `<p class="capture-warning">${safe(warning)}</p>`).join("")}<label for="document-page-${index}">Confirm or correct the extracted text</label><textarea id="document-page-${index}" data-page="${index}" rows="5" maxlength="12000">${safe(draft.reviewedPages?.[index]?.text ?? page.text)}</textarea></div>`).join("");
    document.querySelectorAll("#document-pages textarea").forEach(input => input.addEventListener("input", () => {
      documentDraft.reviewedPages = [...document.querySelectorAll("#document-pages textarea")].map(page => ({ text: page.value }));
      app.offline.put("drafts", documentDraft).catch(error => app.toast(error.message, true));
    }));
    app.go("capture");
    $("#document-review").scrollIntoView({ block: "start", behavior: "smooth" });
  }

  async function extractDraft(draft) {
    if (draft.receipt) { showDocument(draft); return; }
    if (!app.offline.reachable) return app.toast("Scan saved on this device. Reconnect to extract its text.");
    const suffix = draft.filename.split(".").pop().toLowerCase();
    const content = ["txt", "eml"].includes(suffix) ? await draft.blob.text() : await blobBase64(draft.blob);
    draft.receipt = await app.post("/api/documents/extract", { filename: draft.filename, content, handwriting: draft.handwriting });
    await app.offline.put("drafts", draft); notify(); showDocument(draft);
  }

  async function uploadDocument(file) {
    if (!file) return;
    const button = $("#upload-document"), original = button.innerHTML;
    button.disabled = true; button.textContent = "Extracting report…";
    try {
      if (file.size > 10000000) throw new Error("Choose a document of 10 MB or less.");
      const draft = { id: app.offline.id(), kind: "document", filename: file.name, blob: file, savedAt: new Date().toISOString(), scheduleVersion: app.getSchedule(), handwriting: $("#diary-handwriting").checked, ...metadata() };
      await app.offline.put("drafts", draft); notify();
      if (!app.offline.reachable) app.toast("Document saved on this device. Extract it when connected.");
      else await extractDraft(draft);
    } catch (error) { app.toast(error.message, true); }
    finally { button.disabled = false; button.innerHTML = original; $("#document-file").value = ""; }
  }

  async function submitDocument() {
    if (!documentDraft?.receipt) return;
    const button = $("#document-submit");
    button.disabled = true;
    try {
      const pages = [...document.querySelectorAll("#document-pages textarea")].map(input => ({ text: input.value }));
      if (!pages.some(page => page.text.trim())) throw new Error("Add readable report text before submitting.");
      const payload = { source_kind: "document", capture_asset_id: documentDraft.receipt.capture_asset_id, filename: documentDraft.filename,
        reviewed_pages: pages, ...metadata(), analysis_mode: app.isAi() ? "ai" : "rules", schedule_version: documentDraft.scheduleVersion || app.getSchedule(), client_request_id: app.offline.id() };
      if (!app.offline.reachable) {
        await app.offline.enqueue(payload);
        app.toast("Reviewed document saved for submission when connected.");
      } else {
        try { const result = await app.post("/api/reports", payload); app.toast(result.duplicate ? "Repeat document retained in its existing source group." : `${result.events.length} document events ready for planner review.`); }
        catch (error) {
          if (error.status === 409) { await app.offline.enqueue(payload, { status: "conflict", error: error.message }); app.toast("Document saved. Review it against the current schedule in Saved on this device."); }
          else { if (!error.transport) throw error; await app.offline.enqueue(payload); app.toast("Reviewed document saved for submission when connected."); }
        }
      }
      await app.offline.remove("drafts", documentDraft.id); documentDraft = null; notify();
      $("#document-review").hidden = true;
      await app.refresh(); app.go("review");
    } catch (error) { app.toast(error.message, true); }
    finally { button.disabled = false; }
  }

  async function openDraft(draft) {
    for (const [key, selector] of [["event_date", "#report-date"], ["discipline", "#report-discipline"], ["location", "#report-location"]]) $(selector).value = draft[key] || "";
    app.go("capture");
    try { if (draft.kind === "voice") showVoice(draft); else await extractDraft(draft); }
    catch (error) { app.toast(error.message, true); }
  }

  return {
    get voiceSource() { return voiceSource; },
    restoreVoiceSource(source) { voiceSource = source; $("#report-source-note").hidden = false; },
    clearVoiceSource() { voiceSource = null; $("#report-source-note").hidden = true; },
    uploadDocument, openDraft,
    async completeVoice() {
      if (voiceSource) await app.offline.remove("drafts", voiceSource.draftId);
      voiceSource = null; $("#report-source-note").hidden = true; notify();
    },
    init(callbacks) {
      app = callbacks;
      $("#voice-record").addEventListener("click", toggleRecording);
      $("#voice-transcribe").addEventListener("click", transcribe);
      $("#voice-use").addEventListener("click", async () => {
        const text = $("#voice-text").value.trim();
        if (!voiceDraft?.receipt || !text) return app.toast("Transcribe the recording and check its text first.", true);
        if ($("#report-text").value.trim() && !window.confirm("Replace the current report text with this transcript?")) return;
        $("#report-text").value = text;
        voiceSource = { assetId: voiceDraft.receipt.capture_asset_id, draftId: voiceDraft.id, filename: voiceDraft.filename, scheduleVersion: voiceDraft.scheduleVersion };
        $("#report-source-note").hidden = false;
        $("#report-text").focus();
        $("#report-text").dispatchEvent(new Event("input", { bubbles: true }));
      });
      $("#voice-text").addEventListener("input", () => {
        if (!voiceDraft?.receipt) return;
        voiceDraft.receipt.text = $("#voice-text").value;
        app.offline.put("drafts", voiceDraft).catch(error => app.toast(error.message, true));
      });
      $("#document-submit").addEventListener("click", submitDocument);
      $("#document-close").addEventListener("click", () => { $("#document-review").hidden = true; documentDraft = null; });
      window.addEventListener("pagehide", () => { if (recorder?.state === "recording") recorder.stop(); stream?.getTracks().forEach(track => track.stop()); });
    },
  };
})();
