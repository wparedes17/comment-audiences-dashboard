function renderWeeklySentimentChart(canvasId, jsonUrl) {
  fetch(jsonUrl)
    .then((response) => response.json())
    .then((weeks) => {
      const canvas = document.getElementById(canvasId);
      if (!canvas) return;

      if (weeks.length === 0) {
        canvas.replaceWith(document.createTextNode("No sentiment data yet for this publication."));
        return;
      }

      new Chart(canvas, {
        type: "bar",
        data: {
          labels: weeks.map((week) => week.week_start_date),
          datasets: [
            { label: "Positive", data: weeks.map((week) => week.positive_count), backgroundColor: "#2e7d32" },
            { label: "Neutral", data: weeks.map((week) => week.neutral_count), backgroundColor: "#757575" },
            { label: "Negative", data: weeks.map((week) => week.negative_count), backgroundColor: "#c62828" },
          ],
        },
        options: {
          responsive: true,
          scales: { x: { stacked: true }, y: { stacked: true, beginAtZero: true } },
        },
      });
    });
}
