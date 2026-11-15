"use strict";

(function () {
  var SENDER_KEY = "agrichat-sim-id";
  var SOW_WINDOW = "11-01/11-30";
  var CROPS = [
    { key: "rice", label: "Rice" },
    { key: "mungbean", label: "Mungbean" },
    { key: "soybean", label: "Soybean" },
  ];

  function senderId() {
    var id = null;
    try {
      id = window.sessionStorage.getItem(SENDER_KEY);
    } catch (error) {
      id = null;
    }
    if (id) {
      return id;
    }
    var bytes = new Uint8Array(16);
    window.crypto.getRandomValues(bytes);
    id =
      "sim-" +
      Array.prototype.map
        .call(bytes, function (byte) {
          return ("0" + byte.toString(16)).slice(-2);
        })
        .join("");
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

  function setupSimulator() {
    var form = document.getElementById("sim-form");
    if (!form) {
      return;
    }
    var input = document.getElementById("sim-input");
    var send = document.getElementById("sim-send");
    var log = document.getElementById("sim-log");
    var status = document.getElementById("sim-status");
    var sender = senderId();

    function setStatus(message, state) {
      status.textContent = message;
      status.dataset.state = state || "";
    }

    function setBusy(busy) {
      send.disabled = busy;
      Array.prototype.forEach.call(document.querySelectorAll(".chip"), function (chip) {
        chip.disabled = busy;
      });
    }

    function addMessage(node) {
      var empty = document.getElementById("sim-empty");
      if (empty) {
        empty.remove();
      }
      log.appendChild(node);
      log.scrollTop = log.scrollHeight;
    }

    function addReply(data) {
      var group = element("div", "reply");
      var out = element("p", "bubble bubble-out");
      out.lang = "fil";
      out.appendChild(element("span", "bubble-tag", "AgriChat (Filipino)"));
      out.appendChild(document.createTextNode(data.reply));
      out.appendChild(element("span", "bubble-meta", data.length + "/150 characters"));
      group.appendChild(out);
      if (data.translation) {
        var gloss = element("p", "bubble bubble-gloss");
        gloss.lang = "en";
        gloss.appendChild(element("span", "bubble-tag", "English translation"));
        gloss.appendChild(document.createTextNode(data.translation));
        group.appendChild(gloss);
      }
      addMessage(group);
    }

    function submit(text) {
      var message = text.trim();
      if (!message) {
        return;
      }
      var mine = element("p", "bubble bubble-in");
      mine.appendChild(element("span", "bubble-tag", "You"));
      mine.appendChild(document.createTextNode(message));
      addMessage(mine);
      input.value = "";
      setBusy(true);
      setStatus("Waiting for the reply.");
      fetch("/simulate", {
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
          if (!result.ok) {
            var detail = typeof result.data.detail === "string" ? result.data.detail : "";
            setStatus(detail || "The message could not be sent. Check it and try again.", "error");
            return;
          }
          setStatus("");
          addReply(result.data);
        })
        .catch(function () {
          setStatus("Could not reach the server. Try again in a moment.", "error");
        })
        .then(function () {
          setBusy(false);
          input.focus();
        });
    }

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      submit(input.value);
    });
    Array.prototype.forEach.call(document.querySelectorAll(".chip"), function (chip) {
      chip.addEventListener("click", function () {
        submit(chip.dataset.text);
      });
    });
  }

  function share(adequate, total) {
    return total > 0 ? Math.round((adequate / total) * 100) : null;
  }

  function summarize(rows) {
    return CROPS.map(function (crop) {
      var row = rows.find(function (candidate) {
        return candidate.crop === crop.key && candidate.sow_window === SOW_WINDOW;
      });
      if (!row) {
        return null;
      }
      var normalYears = row.n_years - row.n_elnino;
      var normalAdequate = row.n_adequate - row.n_adequate_elnino;
      return {
        label: crop.label,
        normal: share(normalAdequate, normalYears),
        normalText: normalAdequate + " of " + normalYears,
        elnino: share(row.n_adequate_elnino, row.n_elnino),
        elninoText: row.n_adequate_elnino + " of " + row.n_elnino,
      };
    }).filter(Boolean);
  }

  function cssColor(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function setupChart() {
    var canvas = document.getElementById("rotation-chart");
    if (!canvas) {
      return;
    }
    var status = document.getElementById("chart-status");
    var table = document.getElementById("chart-table");
    var body = document.getElementById("chart-rows");
    var chart = null;
    var summary = [];

    function draw() {
      if (!window.Chart || !summary.length) {
        return;
      }
      if (chart) {
        chart.destroy();
      }
      var text = cssColor("--text");
      var grid = cssColor("--chart-grid");
      window.Chart.defaults.font.family = cssColor("--font");
      chart = new window.Chart(canvas, {
        type: "bar",
        data: {
          labels: summary.map(function (item) {
            return item.label;
          }),
          datasets: [
            {
              label: "Normal years",
              data: summary.map(function (item) {
                return item.normal;
              }),
              backgroundColor: cssColor("--chart-normal"),
              borderColor: cssColor("--stem-green"),
              borderWidth: 1,
            },
            {
              label: "El Niño years",
              data: summary.map(function (item) {
                return item.elnino;
              }),
              backgroundColor: cssColor("--chart-elnino"),
              borderColor: cssColor("--ink"),
              borderWidth: 1,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          animation: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? false : {},
          scales: {
            y: {
              min: 0,
              max: 100,
              grid: { color: grid },
              ticks: { color: text, callback: function (value) { return value + "%"; } },
              title: { display: true, text: "Dry seasons with enough water", color: text },
            },
            x: {
              grid: { display: false },
              ticks: { color: text },
              title: { display: true, text: "Crop", color: text },
            },
          },
          plugins: {
            legend: { labels: { color: text } },
            tooltip: {
              callbacks: {
                label: function (context) {
                  return context.dataset.label + ": " + context.parsed.y + "%";
                },
              },
            },
          },
        },
      });
    }

    function fill() {
      body.replaceChildren();
      summary.forEach(function (item) {
        var tr = document.createElement("tr");
        var head = element("th", "", item.label);
        head.scope = "row";
        tr.appendChild(head);
        tr.appendChild(element("td", "", item.normalText + " (" + item.normal + "%)"));
        tr.appendChild(element("td", "", item.elninoText + " (" + item.elnino + "%)"));
        body.appendChild(tr);
      });
      table.hidden = false;
    }

    fetch("/indicators/BATAC")
      .then(function (response) {
        if (!response.ok) {
          throw new Error("status " + response.status);
        }
        return response.json();
      })
      .then(function (rows) {
        summary = summarize(rows);
        if (!summary.length) {
          status.textContent = "No indicator data is available yet.";
          return;
        }
        fill();
        if (window.Chart) {
          status.textContent = "";
          draw();
        } else {
          status.textContent = "The chart library did not load; the table below has the numbers.";
        }
      })
      .catch(function () {
        status.textContent = "The chart data could not be loaded. Try reloading the page.";
        status.dataset.state = "error";
      });

    window
      .matchMedia("(prefers-color-scheme: dark)")
      .addEventListener("change", function () {
        draw();
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
