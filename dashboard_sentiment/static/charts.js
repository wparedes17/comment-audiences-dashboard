function renderDailySentimentChart(canvasId, jsonUrl) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;

  fetch(jsonUrl)
    .then((response) => {
      if (!response.ok) {
        throw new Error(`Request to ${jsonUrl} failed with status ${response.status}`);
      }
      return response.json();
    })
    .then((days) => {
      if (days.length === 0) {
        canvas.replaceWith(document.createTextNode("No sentiment data yet for this publication."));
        return;
      }

      if (typeof Chart === "undefined") {
        throw new Error("Chart.js did not load");
      }

      new Chart(canvas, {
        type: "bar",
        data: {
          labels: days.map((day) => day.date),
          datasets: [
            { label: "Positive", data: days.map((day) => day.positive_count), backgroundColor: "#2e7d32" },
            { label: "Neutral", data: days.map((day) => day.neutral_count), backgroundColor: "#757575" },
            { label: "Negative", data: days.map((day) => day.negative_count), backgroundColor: "#c62828" },
          ],
        },
        options: {
          responsive: true,
          scales: { x: { stacked: true }, y: { stacked: true, beginAtZero: true } },
        },
      });
    })
    .catch((error) => {
      console.error("renderDailySentimentChart:", error);
      canvas.replaceWith(document.createTextNode("Could not load sentiment chart."));
    });
}
