(() => {
    "use strict";

    const app = document.getElementById("restaurants-app");
    if (!app) return;

    const form = document.getElementById("restaurants-form");
    const button = document.getElementById("get-restaurants");
    const status = document.getElementById("restaurants-status");
    const results = document.getElementById("restaurants-results");
    const resultCount = document.getElementById("restaurants-result-count");
    const meta = document.getElementById("restaurants-response-meta");
    const body = document.getElementById("restaurants-response-body");
    const preview = document.getElementById("restaurants-request-url");
    const fields = ["city", "country", "count"].map((name) => form.elements.namedItem(name));
    const categories = { food: "Food", drink: "Drink", service: "Service", vibes: "Vibes", value: "Value" };

    function element(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function requestUrl() {
        const url = new URL(app.dataset.restaurantsUrl, window.location.origin);
        for (const input of fields) {
            const value = input.value.trim();
            if (value !== "") url.searchParams.set(input.name, value);
        }
        return `${url.pathname}${url.search}`;
    }

    function updatePreview() {
        const url = requestUrl();
        preview.textContent = url;
        preview.href = url;
    }

    function emptyState(title, description) {
        const empty = element("div", "empty-state");
        empty.append(element("h3", "", title), element("p", "", description));
        results.replaceChildren(empty);
    }

    function score(value) {
        return typeof value === "number" && Number.isFinite(value) ? value.toFixed(1) : "—";
    }

    function renderRestaurants(restaurants) {
        resultCount.textContent = `${restaurants.length} returned`;
        resultCount.hidden = false;
        if (!restaurants.length) {
            emptyState("No restaurants returned", "Try clearing your filters, checking the location names, or increasing the count.");
            return;
        }
        const cards = restaurants.map((restaurant) => {
            const card = element("article", "restaurant-card");
            const header = element("div", "review-card-header");
            const title = element("div", "restaurant-card-name");
            title.append(
                element("p", "eyebrow", `Restaurant #${restaurant.id}`),
                element("h3", "", restaurant.name),
                element("p", "restaurant-location", [restaurant.city, restaurant.country].filter(Boolean).join(", ") || "Location not provided"),
            );
            const total = element("div", "review-score", restaurant.total_reviews > 0 ? score(restaurant.total_average) : "—");
            total.append(element("small", "", " / 100"));
            header.append(title, total);
            const chips = element("div", "score-chips");
            for (const [key, label] of Object.entries(categories)) {
                const chip = element("span", "score-chip", `${label} `);
                chip.append(element("strong", "", score(restaurant.average_score?.[`${key}_avg`])));
                chips.append(chip);
            }
            const footer = element("div", "restaurant-card-footer");
            footer.append(
                element("span", "", `${restaurant.total_reviews} review${restaurant.total_reviews === 1 ? "" : "s"}`),
                element("span", "koala-score", `🐨 ${restaurant.koalas} / 5 koalas`),
            );
            card.append(header, chips, footer);
            return card;
        });
        results.replaceChildren(...cards);
    }

    form.addEventListener("input", updatePreview);
    form.addEventListener("reset", () => {
        // Reset values are applied after the reset event finishes.
        queueMicrotask(updatePreview);
    });
    updatePreview();

    if (app.dataset.authenticated !== "true") return;

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (button.disabled || !form.reportValidity()) return;
        const url = requestUrl();
        const started = performance.now();
        button.disabled = true;
        button.textContent = "Loading…";
        status.hidden = true;
        resultCount.hidden = true;
        results.setAttribute("aria-busy", "true");
        emptyState("Loading restaurants…", "Waiting for the local backend.");
        meta.textContent = `GET ${url}`;
        body.textContent = "Waiting for the response…";

        try {
            let response;
            try {
                response = await fetch(url, {
                    credentials: "same-origin",
                    headers: { Accept: "application/json" },
                });
                body.textContent = await response.text();
            } catch {
                body.textContent = "No response received.";
                throw new Error("Can’t reach the local backend. Make sure Django is running, then try again.");
            }
            const elapsed = Math.round(performance.now() - started);
            meta.textContent = `HTTP ${response.status} · ${elapsed} ms · GET ${url}`;
            let data;
            try {
                data = JSON.parse(body.textContent);
                body.textContent = JSON.stringify(data, null, 2);
            } catch {
                throw new Error(`The backend returned a non-JSON response (HTTP ${response.status}). Inspect the raw response body below.`);
            }
            if (!response.ok) {
                if (response.status === 401 || response.status === 403) {
                    throw new Error("Your session has expired or access was denied. Sign in again, then refresh this page.");
                }
                throw new Error(typeof data?.detail === "string" ? data.detail : `Request failed (HTTP ${response.status}). Inspect the raw response body below.`);
            }
            if (!Array.isArray(data)) {
                throw new Error("Expected a list of restaurants. Inspect the raw response body below.");
            }
            renderRestaurants(data);
        } catch (error) {
            status.textContent = error.message;
            status.classList.add("notice-error");
            status.hidden = false;
            emptyState("Couldn’t load restaurants", "Check the message above and try your request again.");
            if (body.textContent === "No response received.") meta.textContent = `Network error · GET ${url}`;
        } finally {
            results.setAttribute("aria-busy", "false");
            button.disabled = false;
            button.textContent = "Get restaurants →";
        }
    });
})();