let currentThreadId = localStorage.getItem("travel_thread_id") || null;
let latestAnswerMarkdown = "";

function setPrompt(text) {
    document.getElementById("userInput").value = text;
}

function setLoading(isLoading) {
    const sendBtn = document.getElementById("sendBtn");
    const btnText = document.getElementById("btnText");
    const btnLoader = document.getElementById("btnLoader");

    sendBtn.disabled = isLoading;

    if (isLoading) {
        btnText.classList.add("hidden");
        btnLoader.classList.remove("hidden");
    } else {
        btnText.classList.remove("hidden");
        btnLoader.classList.add("hidden");
    }
}

function showError(message) {
    const errorBox = document.getElementById("errorBox");

    errorBox.textContent = message;
    errorBox.classList.remove("hidden");
}

function hideError() {
    const errorBox = document.getElementById("errorBox");

    errorBox.classList.add("hidden");
    errorBox.textContent = "";
}

function showResult(data) {
    const answer = data.answer || "";
    latestAnswerMarkdown = answer;

    const resultSection = document.getElementById("resultSection");
    const resultTitle = document.getElementById("resultTitle");
    const resultBox = document.getElementById("resultBox");
    const threadInfo = document.getElementById("threadInfo");
    const hitlPanel = document.getElementById("hitlPanel");
    const hitlPrompt = document.getElementById("hitlPrompt");
    const hitlFeedback = document.getElementById("hitlFeedback");
    const guardrailNotice = document.getElementById("guardrailNotice");

    if (typeof marked !== "undefined") {
        resultBox.innerHTML = marked.parse(answer);
    } else {
        resultBox.innerText = answer;
    }

    threadInfo.textContent = `Thread ID: ${data.thread_id}`;

    if (data.guardrail_allowed === false) {
        resultTitle.textContent = "Request Blocked by Guardrail";
        guardrailNotice.textContent = data.guardrail_reason || "Only travel-planning requests are allowed.";
        guardrailNotice.classList.remove("hidden");
    } else {
        guardrailNotice.classList.add("hidden");
        guardrailNotice.textContent = "";
    }

    if (data.requires_approval) {
        resultTitle.textContent = "Draft Itinerary (Awaiting Your Approval)";
        hitlPrompt.textContent =
            data.approval_request ||
            "Review the draft itinerary below. Approve to finalize or request revisions.";
        hitlFeedback.value = "";
        hitlPanel.classList.remove("hidden");
    } else {
        if (data.guardrail_allowed !== false) {
            resultTitle.textContent = "Your AI Travel Plan";
        }
        hitlPanel.classList.add("hidden");
    }

    resultSection.classList.remove("hidden");

    resultSection.scrollIntoView({
        behavior: "smooth",
        block: "start"
    });
}

function setApprovalLoading(isLoading) {
    const approveBtn = document.getElementById("approveBtn");
    const reviseBtn = document.getElementById("reviseBtn");
    if (approveBtn) approveBtn.disabled = isLoading;
    if (reviseBtn) reviseBtn.disabled = isLoading;
}

async function submitApproval(approved) {
    hideError();

    if (!currentThreadId) {
        showError("No active travel thread found.");
        return;
    }

    const feedback = document.getElementById("hitlFeedback").value.trim();
    if (!approved && !feedback) {
        showError("Please enter revision feedback before requesting changes.");
        return;
    }

    setApprovalLoading(true);
    setLoading(true);

    try {
        const response = await fetch("/api/travel/approve", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                thread_id: currentThreadId,
                approved: approved,
                feedback: feedback
            })
        });

        const data = await response.json();

        if (!response.ok || !data.success) {
            throw new Error(data.error || "Could not submit approval.");
        }

        showResult(data);
    } catch (error) {
        showError(error.message);
    } finally {
        setApprovalLoading(false);
        setLoading(false);
    }
}

async function sendMessage() {
    hideError();

    const input = document.getElementById("userInput");
    const message = input.value.trim();

    if (!message) {
        showError("Please enter your travel request first.");
        return;
    }

    setLoading(true);

    try {
        const response = await fetch("/api/travel", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                message: message,
                thread_id: currentThreadId
            })
        });

        const data = await response.json();

        if (!response.ok || !data.success) {
            throw new Error(data.error || "Something went wrong.");
        }

        currentThreadId = data.thread_id;
        localStorage.setItem("travel_thread_id", currentThreadId);

        showResult(data);

    } catch (error) {
        showError(error.message);
    } finally {
        setLoading(false);
    }
}

function copyResult() {
    const resultBox = document.getElementById("resultBox");
    const text = resultBox.innerText;

    if (!text) {
        return;
    }

    navigator.clipboard.writeText(text)
        .then(() => {
            const copyBtn = document.querySelector(".copy-btn");
            const oldText = copyBtn.textContent;

            copyBtn.textContent = "Copied!";

            setTimeout(() => {
                copyBtn.textContent = oldText;
            }, 1400);
        })
        .catch(() => {
            showError("Could not copy result.");
        });
}

function downloadPDF() {
    const pdfContent = document.getElementById("pdfContent");

    if (!latestAnswerMarkdown || !pdfContent) {
        showError("No travel plan available to download.");
        return;
    }

    const downloadBtn = document.querySelector(".download-btn");
    const oldText = downloadBtn.textContent;

    downloadBtn.textContent = "Preparing PDF...";
    downloadBtn.disabled = true;

    const options = {
        margin: 0.5,
        filename: "ai-travel-plan.pdf",
        image: {
            type: "jpeg",
            quality: 0.98
        },
        html2canvas: {
            scale: 2,
            useCORS: true,
            backgroundColor: "#ffffff"
        },
        jsPDF: {
            unit: "in",
            format: "a4",
            orientation: "portrait"
        },
        pagebreak: {
            mode: ["avoid-all", "css", "legacy"]
        }
    };

    html2pdf()
        .set(options)
        .from(pdfContent)
        .save()
        .then(() => {
            downloadBtn.textContent = oldText;
            downloadBtn.disabled = false;
        })
        .catch(() => {
            downloadBtn.textContent = oldText;
            downloadBtn.disabled = false;
            showError("Could not download PDF.");
        });
}

document.addEventListener("keydown", function (event) {
    if (event.ctrlKey && event.key === "Enter") {
        sendMessage();
    }
});