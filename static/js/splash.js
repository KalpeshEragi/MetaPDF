document.addEventListener("DOMContentLoaded", function () {
    setTimeout(() => {
        document.body.style.transition = "opacity 1.5s ease";
        document.body.style.opacity = "0";

        setTimeout(() => {
            window.location.href = "/home"; // Ensure `/main` exists in `chat_app.py`
        }, 1500);
    }, 7000); // 7 seconds display time
});
