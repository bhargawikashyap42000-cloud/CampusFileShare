document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-toggle='password']").forEach((button) => {
        button.addEventListener("click", () => {
            const input = button.parentElement.querySelector("input");
            if (!input) return;
            input.type = input.type === "password" ? "text" : "password";
            button.textContent = input.type === "password" ? "Show" : "Hide";
        });
    });

    const fileInput = document.getElementById("fileInput");
    const fileName = document.getElementById("fileName");
    if (fileInput && fileName) {
        fileInput.addEventListener("change", () => {
            fileName.textContent = fileInput.files.length ? fileInput.files[0].name : "Drop a file here or browse";
        });
    }

    const menu = document.getElementById("mobileMenu");
    const sidebar = document.getElementById("sidebar");
    if (menu && sidebar) menu.addEventListener("click", () => sidebar.classList.toggle("open"));

    document.querySelectorAll(".flash").forEach((item) => {
        window.setTimeout(() => item.classList.add("fade-out"), 4500);
    });
});
