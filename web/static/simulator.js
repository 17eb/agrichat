"use strict";

(function () {
  var SENDER_KEY = "agrichat-sim-id";
  var STEPS = ["REG BATAC ULAN", "LAST PALAY", "PLANT", "WHY"];
  // Which step comes next after each reply template; templates not listed keep the current step.
  var NEXT_STEP = {
    T_REG_OK: 1,
    T_IRRIGATED: 1,
    T_IRRIGATED_NO_DATA: 1,
    T_LAST_OK: 2,
    T_PRIO_OK: 2,
    T_PLANT: 3,
    T_PLANT_BORDER: 3,
    T_WHY: 4,
    T_NO_DATA: 0,
    T_STOP_OK: 0,
  };
  var REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)");

  function newSenderId() {
    var bytes = new Uint8Array(16);
    window.crypto.getRandomValues(bytes);
    return (
      "sim-" +
      Array.prototype.map
        .call(bytes, function (byte) {
          return ("0" + byte.toString(16)).slice(-2);
        })
        .join("")
    );
  }

  function senderId(fresh) {
    var id = null;
    if (!fresh) {
      try {
        id = window.sessionStorage.getItem(SENDER_KEY);
      } catch (error) {
        id = null;
      }
    }
    if (id) {
      return id;
    }
    id = newSenderId();
    try {
      window.sessionStorage.setItem(SENDER_KEY, id);
    } catch (error) {
      /* storage unavailable: the id lasts for this page view only */
    }
    return id;
  }

  function element(tag, className, text) {
    var node = document.createElement(tag);
    if (className) {
      node.className = className;
    }
    if (text !== undefined) {
      node.textContent = text;
    }
    return node;
  }

  function wait(ms) {
    return new Promise(function (resolve) {
      window.setTimeout(resolve, REDUCED_MOTION.matches ? Math.min(ms, 300) : ms);
    });
  }

  function setupSimulator() {
    var form = document.getElementById("sim-form");
    if (!form) {
      return;
    }
    var input = document.getElementById("sim-input");
    var send = document.getElementById("sim-send");
    var log = document.getElementById("sim-log");
    var status = document.getElementById("sim-status");
    var suggest = document.getElementById("sim-suggest");
    var next = suggest.querySelector(".chip-next");
    var steps = document.querySelectorAll("#sim-steps .step");
    var play = document.getElementById("sim-play");
    var translate = document.getElementById("sim-translate");
    var sender = senderId(false);
    var step = 0;
    var busy = false;
    var playing = false;

    function setStatus(message, state) {
      status.textContent = message;
      status.dataset.state = state || "";
    }

    function setBusy(value) {
      busy = value;
      send.disabled = value;
      Array.prototype.forEach.call(suggest.querySelectorAll(".chip"), function (chip) {
        chip.disabled = value || playing;
      });
      play.disabled = value || playing;
    }

    function setStep(value) {
      step = value;
      Array.prototype.forEach.call(steps, function (item, index) {
        item.classList.toggle("is-done", index < step);
        item.classList.toggle("is-current", index === step);
      });
      if (step < STEPS.length) {
        next.hidden = false;
        next.textContent = STEPS[step];
        next.dataset.text = STEPS[step];
      } else {
        next.hidden = true;
      }
    }

    function scrollToEnd() {
      log.scrollTop = log.scrollHeight;
    }

    function addNode(node) {
      var empty = document.getElementById("sim-empty");
      if (empty) {
        empty.remove();
      }
      log.appendChild(node);
      scrollToEnd();
      return node;
    }

    function addMine(text) {
      var group = element("div", "msg msg-me");
      group.appendChild(element("p", "bubble", text));
      addNode(group);
    }

    function addTyping() {
      var group = element("div", "msg msg-them");
      group.setAttribute("aria-hidden", "true");
      var bubble = element("p", "bubble typing");
      bubble.appendChild(document.createElement("i"));
      bubble.appendChild(document.createElement("i"));
      bubble.appendChild(document.createElement("i"));
      group.appendChild(bubble);
      return addNode(group);
    }

    function addReply(data) {
      var group = element("div", "msg msg-them");
      var out = element("p", "bubble", data.reply);
      out.lang = "fil";
      group.appendChild(out);
      if (data.translation) {
        var gloss = element("p", "gloss");
        gloss.lang = "en";
        gloss.appendChild(element("span", "gloss-tag", "EN"));
        gloss.appendChild(document.createTextNode(data.translation));
        group.appendChild(gloss);
      }
      group.appendChild(element("p", "meta", data.length + " of 150 characters"));
      addNode(group);
    }

    function addHint(text) {
      addNode(element("p", "hint", text));
    }

    function advance(templateId) {
      if (Object.prototype.hasOwnProperty.call(NEXT_STEP, templateId)) {
        setStep(NEXT_STEP[templateId]);
      }
      if (templateId === "T_FALLBACK" && step < STEPS.length) {
        addHint("AgriChat understands short keywords. Next, try " + STEPS[step] + ".");
      } else if (templateId === "T_WHY") {
        addHint("That is the whole exchange. Tap Start over to try again.");
      }
    }

    function submit(text) {
      var message = text.trim();
      if (!message || busy) {
        return Promise.resolve();
      }
      addMine(message);
      input.value = "";
      setBusy(true);
      setStatus("");
      var started = Date.now();
      var typing = null;
      var typingTimer = window.setTimeout(function () {
        typing = addTyping();
      }, 250);
      return fetch("/simulate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ from: sender, text: message }),
      })
        .then(function (response) {
          return response.json().then(function (data) {
            return { ok: response.ok, data: data };
          });
        })
        .then(function (result) {
          // Keep the typing dots up briefly so the reply reads as a reply, not a flash.
          return wait(Math.max(0, 700 - (Date.now() - started))).then(function () {
            return result;
          });
        })
        .then(function (result) {
          window.clearTimeout(typingTimer);
          if (typing) {
            typing.remove();
          }
          if (!result.ok) {
            var detail = typeof result.data.detail === "string" ? result.data.detail : "";
            setStatus(detail || "The message could not be sent. Check it and try again.", "error");
            return;
          }
          addReply(result.data);
          advance(result.data.template_id);
        })
        .catch(function () {
          window.clearTimeout(typingTimer);
          if (typing) {
            typing.remove();
          }
          setStatus("Could not reach the server. Try again in a moment.", "error");
        })
        .then(function () {
          setBusy(false);
          if (!playing) {
            input.focus({ preventScroll: true });
          }
        });
    }

    function reset() {
      sender = senderId(true);
      log.replaceChildren();
      var empty = element("p", "phone-empty");
      empty.id = "sim-empty";
      empty.appendChild(document.createTextNode("Tap "));
      empty.appendChild(element("strong", "", STEPS[0]));
      empty.appendChild(document.createTextNode(" below to start."));
      log.appendChild(empty);
      setStatus("");
      setStep(0);
    }

    function playAll() {
      if (busy || playing) {
        return;
      }
      reset();
      playing = true;
      setBusy(false);
      var chain = Promise.resolve();
      STEPS.forEach(function (text) {
        chain = chain
          .then(function () {
            return wait(600);
          })
          .then(function () {
            if (status.dataset.state === "error") {
              throw new Error("stopped");
            }
            return submit(text);
          });
      });
      chain
        .catch(function () {
          /* an error status is already shown */
        })
        .then(function () {
          playing = false;
          setBusy(false);
        });
    }

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      submit(input.value);
    });
    suggest.addEventListener("click", function (event) {
      var chip = event.target.closest(".chip");
      if (!chip || chip.disabled) {
        return;
      }
      if (chip.hasAttribute("data-reset")) {
        reset();
        return;
      }
      submit(chip.dataset.text);
    });
    play.addEventListener("click", function () {
      document.getElementById("simulator").scrollIntoView({
        behavior: REDUCED_MOTION.matches ? "auto" : "smooth",
        block: "center",
      });
      playAll();
    });
    translate.addEventListener("click", function () {
      var on = translate.getAttribute("aria-pressed") !== "true";
      translate.setAttribute("aria-pressed", on ? "true" : "false");
      log.classList.toggle("no-gloss", !on);
      scrollToEnd();
    });

    setStep(0);
  }

  function setupChart() {
    var chart = document.getElementById("water-chart");
    if (!chart) {
      return;
    }
    var control = chart.querySelector(".segmented");
    var bars = chart.querySelector(".bars");
    var segments = control.querySelectorAll(".segment");
    control.hidden = false;
    control.addEventListener("click", function (event) {
      var segment = event.target.closest(".segment");
      if (!segment) {
        return;
      }
      bars.dataset.mode = segment.dataset.mode;
      Array.prototype.forEach.call(segments, function (item) {
        item.setAttribute("aria-pressed", item === segment ? "true" : "false");
      });
    });
  }

  function start() {
    setupSimulator();
    setupChart();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
