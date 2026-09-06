const BACKEND_HOST = window.location.hostname;
const WS_PORT = 81;

let socket = null;

const connectionStatus =
    document.getElementById("connection-status");

const lastReceived =
    document.getElementById("last-received");

const deviceIp =
    document.getElementById("device-ip");

const lightLevel =
    document.getElementById("light-level");

const barLevel =
    document.getElementById("bar-level");

const connectionButton =
    document.getElementById("connection-button");

const innerIndicator =
    document.querySelector(".inner-indicator");

function connect() {

    socket = new WebSocket(
        `ws://${BACKEND_HOST}:${WS_PORT}`
    );

    deviceIp.textContent = BACKEND_HOST;

    socket.onopen = () => {
        connectionStatus.textContent = "Ok";
        connectionButton.textContent = "Stop Connection";
    };

    socket.onmessage = (event) => {

        const ldrValue = Number(event.data);

        lightLevel.textContent = ldrValue;

        lastReceived.textContent =
            new Date().toLocaleTimeString();

        updateIndicator(ldrValue);
    };

    socket.onclose = () => {
        connectionStatus.textContent = "Disconnected";
        connectionButton.textContent = "Start Connection";
    };

    socket.onerror = () => {
        connectionStatus.textContent = "Error";
    };
}


function disconnect() {

    if (socket) {
        socket.close();
    }
}


function updateIndicator(ldrValue) {

    const minValue = 500;
    const maxValue = 3900;

    let percentage =
        (ldrValue - minValue) /
        (maxValue - minValue);

    if (percentage < 0) {
        percentage = 0;
    }

    if (percentage > 1) {
        percentage = 1;
    }

    // Barra
    barLevel.style.width = `${percentage * 100}%`;

    // Colores definidos en CSS
    const lightOff = [170, 161, 128];
    const lightUp = [255, 236, 169];

    const r =
        lightOff[0] +
        (lightUp[0] - lightOff[0]) * percentage;

    const g =
        lightOff[1] +
        (lightUp[1] - lightOff[1]) * percentage;

    const b =
        lightOff[2] +
        (lightUp[2] - lightOff[2]) * percentage;

    innerIndicator.style.backgroundColor =
        `rgb(${r}, ${g}, ${b})`;

    // Intensidad del aura
    const shadowBlur = 5 + percentage * 20;
    const shadowSpread = percentage * 20;

    innerIndicator.style.boxShadow =
        `0 0 ${shadowBlur}px ${shadowSpread}px var(--color-light-aura)`;
}


connectionButton.addEventListener("click", () => {

    if (
        socket &&
        socket.readyState === WebSocket.OPEN
    ) {
        disconnect();
    }
    else {
        connect();
    }
});


connect();