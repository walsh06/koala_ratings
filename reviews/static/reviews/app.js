(() => {
    "use strict";

    const app = document.getElementById("reviews-app");
    if (!app) return;

    const categories = ["food", "drink", "service", "vibes", "value"];
    const labels = { food: "Food", drink: "Drink", service: "Service", vibes: "Vibes", value: "Value" };
    const authenticated = app.dataset.authenticated === "true";
    const status = document.getElementById("app-status");
    const reviewForm = document.getElementById("review-form");
    const lookupForm = document.getElementById("lookup-form");
    const addRestaurantForm = document.getElementById("add-restaurant-form");
    const addRestaurantButton = document.getElementById("add-restaurant-button");
    const restaurantName = document.getElementById("restaurant-name");
    const restaurantCountry = document.getElementById("restaurant-country");
    const restaurantCity = document.getElementById("restaurant-city");
    const addRestaurantResult = document.getElementById("add-restaurant-result");
    const myReviews = document.getElementById("my-reviews");
    const restaurantReviews = document.getElementById("restaurant-reviews");
    const refreshButton = document.getElementById("refresh-reviews");
    const saveButton = document.getElementById("save-review");
    const lookupButton = document.getElementById("lookup-button");
    let collection = [];
    let collectionLoaded = false;
    let selectedRestaurant = null;
    let collectionRequest = null;
    let lookupRequest = null;

    function element(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function showStatus(message, isError = false) {
        status.textContent = message;
        status.classList.toggle("notice-error", isError);
        status.hidden = false;
    }

    function emptyState(container, title, description) {
        const empty = element("div", "empty-state");
        const icon = element("span", "", "↗");
        icon.setAttribute("aria-hidden", "true");
        empty.append(icon, element("h3", "", title), element("p", "", description));
        container.replaceChildren(empty);
    }

    function formatErrors(data) {
        if (typeof data.detail === "string") return data.detail;
        return Object.entries(data).map(([key, value]) => {
            const message = Array.isArray(value) ? value.join(" ") : String(value);
            return `${labels[key] || key}: ${message}`;
        }).join(" ");
    }

    async function apiRequest(url, options = {}) {
        let response;
        try {
            response = await fetch(url, {
                credentials: "same-origin",
                ...options,
                headers: { Accept: "application/json", ...options.headers },
            });
        } catch (error) {
            if (error.name === "AbortError") throw error;
            throw new Error("Can’t reach the local backend. Make sure Django is running, then try again.");
        }
        let data;
        try {
            data = await response.json();
        } catch {
            throw new Error(`The backend returned an unexpected response (HTTP ${response.status}). Try refreshing the page.`);
        }
        if (!response.ok) {
            if (response.status === 401 || response.status === 403) {
                throw new Error("Your session expired or the security token is no longer valid. Refresh the page and sign in again.");
            }
            const error = new Error(formatErrors(data) || `Request failed (HTTP ${response.status}).`);
            error.status = response.status;
            throw error;
        }
        return data;
    }

    function restaurantUrl(template, id) {
        return template.replace("/0/", `/${id}/`);
    }

    function restaurantId(input) {
        const id = Number(input.value);
        if (!Number.isSafeInteger(id) || id < 1) {
            input.setCustomValidity("Enter a positive whole-number restaurant ID.");
            input.reportValidity();
            return null;
        }
        input.setCustomValidity("");
        return id;
    }

    function updateScorePreview() {
        let total = 0;
        for (const category of categories) {
            const input = document.getElementById(`score-${category}`);
            const score = Number(input.value);
            total += score;
            document.getElementById(`output-${category}`).value = score;
            input.style.setProperty("--range-progress", `${((score - 1) / 19) * 100}%`);
        }
        document.getElementById("review-total").value = total;
    }

    function scoreDisplay(total) {
        const score = element("div", "review-score", total);
        score.append(element("small", "", " / 100"));
        return score;
    }

    function scoreChips(scores) {
        const chips = element("div", "score-chips");
        for (const category of categories) {
            const chip = element("span", "score-chip", `${labels[category]} `);
            chip.append(element("strong", "", scores[category]));
            chips.append(chip);
        }
        return chips;
    }

    function loadReviewIntoForm(review) {
        document.getElementById("review-restaurant-id").value = review.restaurant_id;
        for (const category of categories) {
            document.getElementById(`score-${category}`).value = review.scores[category];
        }
        updateScorePreview();
        reviewForm.scrollIntoView({ block: "center", behavior: "auto" });
        document.getElementById("review-restaurant-id").focus({ preventScroll: true });
        showStatus(`Loaded your review for restaurant #${review.restaurant_id}. Adjust the scores and save to update it.`);
    }

    function renderCollection() {
        document.getElementById("stat-count").textContent = collection.length;
        document.getElementById("stat-average").textContent = collection.length
            ? (collection.reduce((sum, review) => sum + review.your_total, 0) / collection.length).toFixed(1) : "—";
        document.getElementById("stat-best").textContent = collection.length
            ? collection.reduce((best, review) => Math.max(best, review.your_total), 0) : "—";
        if (!collection.length) {
            emptyState(myReviews, "Your first impression awaits", "Review a restaurant and it will appear in your collection.");
            return;
        }
        const cards = collection.map((review) => {
            const card = element("article", "review-card");
            const header = element("div", "review-card-header");
            const title = element("div", "review-card-title");
            const mark = element("span", "restaurant-mark", "r.");
            mark.setAttribute("aria-hidden", "true");
            title.append(mark, element("h3", "", `Restaurant #${review.restaurant_id}`));
            header.append(title, scoreDisplay(review.your_total));
            const actions = element("div", "card-actions");
            const edit = element("button", "text-link", "Edit review");
            edit.type = "button";
            edit.addEventListener("click", () => loadReviewIntoForm(review));
            const view = element("button", "text-link", "See all reviews ↗");
            view.type = "button";
            view.addEventListener("click", () => {
                document.getElementById("lookup-restaurant-id").value = review.restaurant_id;
                lookupForm.scrollIntoView({ block: "center", behavior: "auto" });
                loadRestaurant(review.restaurant_id);
            });
            actions.append(edit, view);
            card.append(header, scoreChips(review.scores), actions);
            return card;
        });
        myReviews.replaceChildren(...cards);
    }

    async function loadCollection() {
        collectionRequest?.abort();
        const controller = new AbortController();
        collectionRequest = controller;
        refreshButton.disabled = true;
        myReviews.setAttribute("aria-busy", "true");
        try {
            collection = await apiRequest(app.dataset.myReviewsUrl, { signal: controller.signal });
            renderCollection();
            collectionLoaded = true;
        } catch (error) {
            if (error.name !== "AbortError") {
                showStatus(error.message, true);
                if (!collectionLoaded) emptyState(myReviews, "Couldn’t load your collection", "Use the refresh button to try again.");
            }
        } finally {
            if (collectionRequest === controller) {
                refreshButton.disabled = false;
                myReviews.setAttribute("aria-busy", "false");
            }
        }
    }

    async function loadRestaurant(id) {
        lookupRequest?.abort();
        const controller = new AbortController();
        lookupRequest = controller;
        selectedRestaurant = id;
        lookupButton.disabled = true;
        lookupButton.textContent = "Loading…";
        restaurantReviews.setAttribute("aria-busy", "true");
        restaurantReviews.replaceChildren(element("p", "input-help", `Loading reviews for restaurant #${id}…`));
        try {
            const reviews = await apiRequest(restaurantUrl(app.dataset.restaurantReviewsUrl, id), { signal: controller.signal });
            if (!reviews.length) {
                emptyState(restaurantReviews, `No reviews for restaurant #${id}`, "Be the first to leave an impression. Review this ID on the left.");
                return;
            }
            const summary = element("div", "lookup-summary");
            const title = element("div");
            title.append(element("h3", "", `Restaurant #${id}`), element("p", "", `${reviews.length} review${reviews.length === 1 ? "" : "s"} · Average score`));
            const average = reviews.reduce((sum, review) => sum + review.total, 0) / reviews.length;
            summary.append(title, scoreDisplay(average.toFixed(1)));
            const list = element("div", "community-list");
            reviews.forEach((review, index) => {
                const card = element("article", "review-card");
                const header = element("div", "review-card-header");
                header.append(element("h3", "", `Review ${index + 1}`), scoreDisplay(review.total));
                card.append(header, scoreChips(review.scores));
                list.append(card);
            });
            restaurantReviews.replaceChildren(summary, list);
        } catch (error) {
            if (error.name !== "AbortError") {
                if (error.status === 404) {
                    emptyState(restaurantReviews, "Restaurant not found", "Check the ID, or add a restaurant first using the Add restaurant form.");
                } else {
                    emptyState(restaurantReviews, "Couldn’t load restaurant reviews", "Try the lookup again when the backend is available.");
                }
                showStatus(error.message, true);
            }
        } finally {
            if (lookupRequest === controller) {
                lookupButton.disabled = false;
                lookupButton.textContent = "Look up";
                restaurantReviews.setAttribute("aria-busy", "false");
            }
        }
    }

    for (const category of categories) {
        document.getElementById(`score-${category}`).addEventListener("input", updateScorePreview);
    }
    for (const id of ["review-restaurant-id", "lookup-restaurant-id"]) {
        document.getElementById(id).addEventListener("input", (event) => event.target.setCustomValidity(""));
    }
    updateScorePreview();
    const restaurantFields = { name: restaurantName, country: restaurantCountry, city: restaurantCity };
    for (const input of Object.values(restaurantFields)) {
        input.addEventListener("input", () => input.setCustomValidity(""));
    }

    if (!authenticated) return;

    addRestaurantForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (addRestaurantButton.disabled) return;
        const details = {};
        for (const [field, input] of Object.entries(restaurantFields)) {
            details[field] = input.value.trim();
            if (!details[field]) {
                input.setCustomValidity(`Enter ${field === "name" ? "a restaurant name" : `a ${field}`}, not just spaces.`);
                input.reportValidity();
                return;
            }
        }
        addRestaurantButton.disabled = true;
        addRestaurantButton.textContent = "Adding…";
        status.hidden = true;
        try {
            const restaurant = await apiRequest(app.dataset.addRestaurantUrl, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": document.querySelector('meta[name="csrf-token"]').content,
                },
                body: JSON.stringify(details),
            });
            const message = `Added ${restaurant.name} in ${restaurant.city}, ${restaurant.country} — restaurant #${restaurant.id}. Its ID is ready in the review form. Choose your scores and save your review.`;
            addRestaurantResult.textContent = message;
            showStatus(message);
            for (const input of Object.values(restaurantFields)) input.value = "";
            const idInput = document.getElementById("review-restaurant-id");
            idInput.setCustomValidity("");
            idInput.value = restaurant.id;
            reviewForm.scrollIntoView({ block: "center", behavior: "auto" });
            idInput.focus({ preventScroll: true });
        } catch (error) {
            addRestaurantResult.textContent = error.message;
            showStatus(error.message, true);
        } finally {
            addRestaurantButton.disabled = false;
            addRestaurantButton.textContent = "Add restaurant →";
        }
    });

    refreshButton.addEventListener("click", () => {
        status.hidden = true;
        loadCollection();
    });

    lookupForm.addEventListener("submit", (event) => {
        event.preventDefault();
        const id = restaurantId(document.getElementById("lookup-restaurant-id"));
        if (id !== null) {
            status.hidden = true;
            loadRestaurant(id);
        }
    });

    reviewForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (saveButton.disabled) return;
        const id = restaurantId(document.getElementById("review-restaurant-id"));
        if (id === null) return;
        const scores = Object.fromEntries(categories.map((category) => [category, Number(document.getElementById(`score-${category}`).value)]));
        saveButton.disabled = true;
        saveButton.textContent = "Saving…";
        status.hidden = true;
        try {
            const review = await apiRequest(restaurantUrl(app.dataset.submitReviewUrl, id), {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": document.querySelector('meta[name="csrf-token"]').content,
                },
                body: JSON.stringify(scores),
            });
            showStatus(`Saved your review for restaurant #${id}: ${review.your_total}/100.`);
            await loadCollection();
            if (selectedRestaurant === id) await loadRestaurant(id);
        } catch (error) {
            showStatus(error.message, true);
        } finally {
            saveButton.disabled = false;
            saveButton.textContent = "Save my review →";
        }
    });

    loadCollection();
})();