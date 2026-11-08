# Koala restaurant ratings

A local Django REST Framework prototype with a Django-served HTML/CSS/JavaScript
frontend. Each of the five categories accepts
whole-number scores from 1 to 20. The user's total is their sum, from 5 to 100.

The endpoint validates and saves ratings to SQLite against the signed-in user and
restaurant ID. Posting again for the same user and restaurant updates that rating.
Restaurants have a database-generated ID, a name, a country, and a city. Rating saves and updates
require an existing restaurant, with a foreign key enforcing this in the database.
Restaurant averages are calculated in the frontend, not the backend.
PostgreSQL/PostGIS and Entra authentication are not configured.

## Local setup

**Migration warning:** the restaurant migration deletes all existing prototype
ratings, as agreed, before introducing restaurant foreign keys. It leaves user
accounts, sessions, and unrelated data intact and does not create placeholder
restaurants. Back up your SQLite database before applying it. Reversing the
migration does not restore deleted ratings. This applies once when upgrading
from the original schema; new installations simply start empty.

The subsequent location migration preserves all restaurants and ratings. Existing
restaurants receive empty country/city fields because their locations are unknown;
these can be filled through the Django ORM. New API creations require both fields.

The review migration renames the Python model to `Review` and the database table
to `ratings_review`, preserving existing scores, timestamps, restaurant links,
and accounts. The serializer and view functions use review terminology too.
The Django app remains `ratings`, and existing API URLs and route names are
unchanged for compatibility. Previously applied migrations retain their
historical model names; run `manage.py migrate` when updating an existing database.

Run these commands in PowerShell from this folder:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py createsuperuser
.\.venv\Scripts\python.exe manage.py runserver
```

The environment and database have already been initialized in the generated
project. Create your own local account with `createsuperuser`; no account or
password is preconfigured.

## Local frontend

With Django running, open **http://127.0.0.1:8000/** and choose **Sign in**.
Use the local account created above. The frontend lets you:

- Enter a name, country, and city in **Add a restaurant**. The returned ID is filled into the
  rating form; creation does not save a rating or reset your score sliders.
- Load and refresh your saved ratings, including your count, average, and best score.
- Enter an existing restaurant ID and set five scores with sliders. The total
  updates as you move them; **Save my rating** persists the scores through the API.
- Choose **Edit rating** to load a saved rating back into the form.
- Look up all ratings for an ID, or choose **See all ratings** on a saved rating.
  The displayed restaurant average is calculated in the browser from the returned
  ratings; it is not a new backend endpoint.
- Sign out safely using a CSRF-protected POST.

No Node.js installation, frontend build, separate frontend server, or CORS setup
is needed. Django serves both the page and the API from the same origin, and
development static-file serving requires `DEBUG = True`. API URLs come from
Django's named routes, so the frontend also works on another local port. Keep
the same hostname while signing in and using the app; `localhost` and
`127.0.0.1` have separate cookies.

The UI shows loading, empty, validation, session-expiry, and connection-error
states. It uses real API responses, not sample ratings. Restaurant names are
stored on creation, but no searchable directory exists yet and rating cards
still identify restaurants by numeric ID.

## VS Code

Open this folder and install the recommended Python and Python Debugger
extensions. Select `.venv\Scripts\python.exe` with **Python: Select Interpreter**
if VS Code does not select it automatically.

For normal development, choose **Terminal → Run Task → Run Koala locally**.
This starts Django at http://127.0.0.1:8000/ with automatic reloading.

Choose **Debug Django** in Run and Debug, then press F5. Set breakpoints in
`ratings\views.py`. The debugger disables automatic reloading; restart it after
editing Python files. Stop debugging with Shift+F5.

## Add a restaurant

Sign in and POST to http://127.0.0.1:8000/api/restaurants/ with a JSON object
containing `name`, `country`, and `city`, for example
`{"name": "The Green Table", "country": "United Kingdom", "city": "London"}`.
The response is **HTTP 201 Created**, for example
`{"id": 1, "name": "The Green Table", "country": "United Kingdom", "city": "London"}`.
Use the returned ID for rating saves and lookups.

Any authenticated user can create a restaurant. All three fields are required,
trimmed, and must be nonblank. Names have a maximum of 200 characters; country
and city each have a maximum of 100. Missing or invalid fields return HTTP 400
with field-specific errors. Locations are free-text names, not country codes
or a validated geographical directory. Duplicate names are allowed.
The ID is read-only; sending an `id` cannot choose the primary key. Creation
does not submit a rating. This endpoint supports POST only; no restaurant
list, search, edit, or delete API is provided.

Session-authenticated requests must send a CSRF token, as the built-in form does.
Anonymous requests return HTTP 403 with the current authentication defaults.

## Submit a rating

1. Sign in at http://127.0.0.1:8000/api-auth/login/.
2. Add a restaurant first using the frontend or the creation API above.
3. Open `/api/restaurants/<returned-id>/submit-rating/` on the local server.
  For an existing ID of 42 this is
  http://127.0.0.1:8000/api/restaurants/42/submit-rating/.
4. The initial GET returns 405 because the endpoint only accepts POST.
   In the browsable API's POST form, select `application/json` and submit:

```json
{
  "food": 18,
  "drink": 15,
  "service": 17,
  "vibes": 19,
  "value": 16
}
```

The response contains `your_total: 85`. Missing categories, scores below 1 or
above 20, and fractional scores return HTTP 400.
An unknown restaurant ID returns HTTP 404 with
`{"detail": "Restaurant not found."}` before any score validation or write.
This applies to updates as well as new ratings and never creates restaurants
automatically. The example ID 42 must exist; use your actual returned ID.

Saved reviews are in the `ratings_review` table in `db.sqlite3`, including the
user ID, restaurant ID, all five scores, and creation/update timestamps. The
total is calculated from the scores rather than stored separately. Database
constraints enforce score bounds, an existing restaurant, and one rating per
user per restaurant. Referenced restaurants are protected from deletion.
Both new ratings and updates return HTTP 200 with the existing response format.

Django REST Framework's default session and basic authentication are used for
local testing. The built-in frontend uses the session and sends a CSRF token
with its POST requests. Its sign-in page redirects to the frontend; the existing
API sign-in page still defaults to your ratings JSON.
Entra bearer tokens are not supported by this prototype. Cross-origin frontend
access is not configured.

## Get your ratings

After signing in, open http://127.0.0.1:8000/api/me/ratings/ or send a GET
request to that URL using your authenticated session. The response is a JSON
array containing only the signed-in user's saved ratings, ordered by restaurant
ID:

```json
[
  {
    "restaurant_id": 42,
    "scores": {
      "food": 18,
      "drink": 15,
      "service": 17,
      "vibes": 19,
      "value": 16
    },
    "your_total": 85
  }
]
```

Users with no ratings receive `[]`. The endpoint returns all their ratings
without pagination. A user ID cannot be selected through query parameters;
the authenticated identity determines whose ratings are returned.

## Get restaurant ratings

After signing in, GET
http://127.0.0.1:8000/api/restaurants/42/ratings/all/ to retrieve all users'
ratings for that ID. Each entry includes `restaurant_id`, `scores`, and `total`.
User identities are not included. An existing restaurant with no ratings returns
`[]`; an unknown restaurant returns HTTP 404. Use the ID returned by creation
rather than assuming the example ID 42 exists.

## Tests

```powershell
.\.venv\Scripts\python.exe manage.py test ratings
.\.venv\Scripts\python.exe manage.py check
```

Alternatively choose **Debug rating tests** and press F5. Tests use a separate
temporary database and cover scoring, persistence, updates, database constraints,
required categories, listing only the current user's ratings, restaurant lookups,
frontend templates, sign-in redirects, and session-authenticated POSTs with
enforced CSRF checks. They do not automate JavaScript or test Entra.
They also cover restaurant creation, missing-ID rejection, foreign key and
deletion protection, and migration from the old schema with prototype-rating
deletion and preservation of user accounts.

## Development only

Settings enable debug mode and use a public development-only secret-key
placeholder unless `DJANGO_SECRET_KEY` is supplied through the environment.
Do not deploy these settings or expose the development server publicly.
