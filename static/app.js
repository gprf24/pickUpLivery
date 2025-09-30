// ----- Geolocation -----
async function captureLocation() {
  if (!navigator.geolocation) {
    alert("Geolocation not supported by your browser");
    return;
  }
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      document.getElementById("lat").value = pos.coords.latitude;
      document.getElementById("lon").value = pos.coords.longitude;
      document.getElementById("geo-status").textContent =
        "📍 Location captured";
    },
    (err) => {
      alert("Error getting location: " + err.message);
    }
  );
}

// ----- Preview image before upload -----
function previewFile(input) {
  const file = input.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (e) => {
    const img = document.getElementById("preview");
    img.src = e.target.result;
    img.style.display = "block";
  };
  reader.readAsDataURL(file);
}

// attach handlers on DOM ready
document.addEventListener("DOMContentLoaded", () => {
  const geoBtn = document.getElementById("geo-btn");
  if (geoBtn) geoBtn.addEventListener("click", captureLocation);

  const fileInput = document.getElementById("image");
  if (fileInput) {
    fileInput.addEventListener("change", () => previewFile(fileInput));
  }
});
