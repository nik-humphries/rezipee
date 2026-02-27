"""
Rezipee — Recipe Manager  (MongoDB-backed)

Design principles
  • Data persisted in MongoDB Atlas — works on Streamlit Community Cloud.
  • Connection string stored in st.secrets (`.streamlit/secrets.toml` locally,
    Streamlit Cloud secrets UI for production).
  • Single shared MongoClient per process (singleton).
  • Load helpers convert Mongo documents → pandas DataFrames (same interface
    the UI already uses).  Save helpers write DataFrames → Mongo collections.
  • Zero st.rerun() calls.  Zero @st.cache_data.
  • All DataFrame columns normalised to safe types on every load.
"""

import streamlit as st
import pandas as pd
import uuid
from datetime import datetime
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure

# ── Page config (must be first Streamlit call) ──────────────────────────────
st.set_page_config(page_title="Rezipee — Recipe Manager", layout="wide")

# ── MongoDB connection (singleton per process) ──────────────────────────────
MONGO_URI = st.secrets["mongo"]["uri"]
MONGO_DB = st.secrets["mongo"]["db"]

@st.cache_resource
def _get_client() -> MongoClient:
    """Return a shared MongoClient.  cached_resource lives for the process."""
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    # Quick connectivity check
    try:
        client.admin.command("ping")
    except ConnectionFailure:
        st.error("⚠️ Cannot reach MongoDB — check your connection string.")
        st.stop()
    return client

_db = _get_client()[MONGO_DB]

# Collection handles
COL_RECIPES = _db["recipes"]
COL_HISTORY = _db["meal_history"]
COL_PANTRY = _db["pantry_staples"]
COL_PRICING = _db["ingredient_pricing"]
COL_PRICE_HIST = _db["price_history"]

# ── Column definitions ──────────────────────────────────────────────────────
RECIPE_COLS = [
    "recipe_id", "recipe_name", "ingredient", "quantity", "unit",
    "category", "tags", "cook_time", "rating", "source", "source_url",
    "servings", "notes", "estimated_cost", "prep_friendly",
]

STR_COLS = [
    "recipe_id", "recipe_name", "ingredient", "unit", "category",
    "tags", "cook_time", "rating", "source", "source_url", "notes",
]


# ── Generic helpers ─────────────────────────────────────────────────────────

def _safe_str_col(df: pd.DataFrame, col: str) -> pd.DataFrame:
    if col in df.columns:
        df[col] = df[col].fillna("").astype(str)
    return df


def _col_to_df(collection, columns: list | None = None) -> pd.DataFrame:
    """Read every document from *collection* into a DataFrame, dropping _id."""
    docs = list(collection.find({}, {"_id": 0}))
    if not docs:
        return pd.DataFrame(columns=columns or [])
    df = pd.DataFrame(docs)
    # Ensure all expected columns exist
    if columns:
        for c in columns:
            if c not in df.columns:
                df[c] = ""
    return df


def _df_to_col(collection, df: pd.DataFrame):
    """Replace **all** documents in *collection* with rows from *df*."""
    records = df.to_dict("records")
    collection.delete_many({})
    if records:
        collection.insert_many(records)


# ── Load helpers ────────────────────────────────────────────────────────────

def _load_recipes() -> pd.DataFrame:
    df = _col_to_df(COL_RECIPES, RECIPE_COLS)
    if df.empty:
        return pd.DataFrame(columns=RECIPE_COLS)
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")
    for col in ["rating", "source", "source_url", "servings", "notes",
                 "estimated_cost", "prep_friendly"]:
        if col not in df.columns:
            df[col] = {"servings": 2, "estimated_cost": 0.0,
                       "prep_friendly": False}.get(col, "")
    df["servings"] = pd.to_numeric(df["servings"], errors="coerce").fillna(2).astype(int)
    df["estimated_cost"] = pd.to_numeric(df["estimated_cost"], errors="coerce").fillna(0.0)
    for c in STR_COLS:
        df = _safe_str_col(df, c)
    return df


def _load_history() -> pd.DataFrame:
    df = _col_to_df(COL_HISTORY, ["week_start", "recipe_name"])
    if "week_start" in df.columns and not df.empty:
        df["week_start"] = pd.to_datetime(df["week_start"], errors="coerce")
    return df


def _load_pantry() -> pd.DataFrame:
    df = _col_to_df(COL_PANTRY, ["ingredient"])
    df = _safe_str_col(df, "ingredient")
    return df


def _load_pricing() -> pd.DataFrame:
    df = _col_to_df(COL_PRICING, ["ingredient", "unit", "price_per_unit", "last_updated"])
    if df.empty:
        return pd.DataFrame(columns=["ingredient", "unit", "price_per_unit", "last_updated"])
    for c in ["ingredient", "unit", "last_updated"]:
        df = _safe_str_col(df, c)
    df["price_per_unit"] = pd.to_numeric(df["price_per_unit"], errors="coerce").fillna(0.0)
    return df


def _load_price_history() -> pd.DataFrame:
    df = _col_to_df(COL_PRICE_HIST,
                     ["ingredient", "unit", "old_price", "new_price", "changed_at"])
    if df.empty:
        return pd.DataFrame(columns=["ingredient", "unit", "old_price", "new_price", "changed_at"])
    for c in ["ingredient", "unit", "changed_at"]:
        df = _safe_str_col(df, c)
    df["old_price"] = pd.to_numeric(df["old_price"], errors="coerce").fillna(0.0)
    df["new_price"] = pd.to_numeric(df["new_price"], errors="coerce").fillna(0.0)
    return df


# ── Save helpers ────────────────────────────────────────────────────────────

def _save_recipes(df: pd.DataFrame):
    _df_to_col(COL_RECIPES, df)
    st.session_state["recipes"] = _load_recipes()


def _save_history(df: pd.DataFrame):
    # Convert Timestamps to ISO strings before storing
    save = df.copy()
    if "week_start" in save.columns:
        save["week_start"] = pd.to_datetime(
            save["week_start"], errors="coerce"
        ).dt.strftime("%Y-%m-%d")
    _df_to_col(COL_HISTORY, save)
    st.session_state["meal_history"] = _load_history()


def _save_pantry(df: pd.DataFrame):
    _df_to_col(COL_PANTRY, df)
    st.session_state["pantry"] = _load_pantry()


def _save_pricing(df: pd.DataFrame):
    """Save pricing and record any price changes in history."""
    existing = _load_pricing()
    history = _load_price_history()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_rows = []

    for _, row in df.iterrows():
        ing = str(row["ingredient"]).strip()
        unit = str(row["unit"]).strip()
        new_price = float(row["price_per_unit"])
        if not existing.empty:
            match = existing[
                (existing["ingredient"].str.lower() == ing.lower())
                & (existing["unit"].str.lower() == unit.lower())
            ]
            old_price = float(match.iloc[0]["price_per_unit"]) if not match.empty else 0.0
        else:
            old_price = 0.0
        if abs(old_price - new_price) > 0.001:
            new_rows.append({
                "ingredient": ing, "unit": unit,
                "old_price": old_price, "new_price": new_price, "changed_at": ts,
            })

    if new_rows:
        history = pd.concat([history, pd.DataFrame(new_rows)], ignore_index=True)
        _df_to_col(COL_PRICE_HIST, history)

    df["last_updated"] = ts
    _df_to_col(COL_PRICING, df)
    st.session_state["pricing"] = _load_pricing()


# ── Session-state bootstrap ────────────────────────────────────────────────

def _init_state():
    defaults = {
        "recipes": _load_recipes,
        "meal_history": _load_history,
        "pantry": _load_pantry,
        "pricing": _load_pricing,
        "weekly_recipes": list,
        "daily_plan": lambda: {d: None for d in
                               ["Monday", "Tuesday", "Wednesday", "Thursday",
                                "Friday", "Saturday", "Sunday"]},
        "recipe_servings": dict,
    }
    for key, factory in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = factory()

_init_state()

# Convenience aliases
recipes: pd.DataFrame = st.session_state["recipes"]
meal_history: pd.DataFrame = st.session_state["meal_history"]
pantry: pd.DataFrame = st.session_state["pantry"]
pricing: pd.DataFrame = st.session_state["pricing"]


# ── Utility functions ───────────────────────────────────────────────────────

def _unique_recipes(df: pd.DataFrame) -> list:
    if df.empty:
        return []
    return sorted(df["recipe_name"].dropna().unique().tolist())


def _unique_safe(series: pd.Series) -> list:
    vals = series.dropna().unique().tolist()
    return sorted({str(v) for v in vals if str(v).strip() and str(v).lower() != "nan"})


def _lookup_price(ing: str, unit: str) -> float:
    if pricing.empty:
        return 0.0
    match = pricing[
        (pricing["ingredient"].str.lower() == ing.lower())
        & (pricing["unit"].str.lower() == unit.lower())
    ]
    return float(match.iloc[0]["price_per_unit"]) if not match.empty else 0.0


def _recipe_cost(recipe_name: str, df: pd.DataFrame = None) -> float:
    src = df if df is not None else recipes
    rows = src[src["recipe_name"] == recipe_name]
    total = 0.0
    for _, r in rows.iterrows():
        total += float(r["quantity"] or 0) * _lookup_price(r["ingredient"], r["unit"])
    return total


def _get_recommendations(top_n: int = 5) -> list:
    if recipes.empty:
        return []
    recs = []
    for name in recipes["recipe_name"].unique():
        row = recipes[recipes["recipe_name"] == name].iloc[0]
        score, reasons = 0, []
        try:
            rv = float(row["rating"])
            score += rv * 10
            if rv >= 4:
                reasons.append(f"⭐ Rated {rv:.0f}/5")
        except (ValueError, TypeError):
            pass
        if not meal_history.empty:
            cooked = meal_history[meal_history["recipe_name"] == name]
            n = len(cooked)
            if n > 0:
                last = cooked["week_start"].max()
                days = (pd.Timestamp.now() - last).days
                if days > 60:
                    score += 15
                    reasons.append(f"🕐 Not cooked in {days} days")
                elif days < 14:
                    score -= 20
                if n >= 3:
                    score += 5
                    reasons.append(f"❤️ Favorite ({n}×)")
            else:
                score += 10
                reasons.append("✨ Never tried")
        else:
            score += 10
            reasons.append("✨ Never tried")
        ct = str(row.get("cook_time", ""))
        if any(t in ct for t in ("15", "20")):
            score += 5
            reasons.append("⚡ Quick meal")
        recs.append({"recipe": name, "score": score,
                      "reasons": " · ".join(reasons) or "Good choice!"})
    recs.sort(key=lambda x: x["score"], reverse=True)
    return recs[:top_n]


# ════════════════════════════════════════════════════════════════════════════
# UI
# ════════════════════════════════════════════════════════════════════════════

st.title("🥘 Rezipee — Recipe Manager")

tab_labels = [
    "🏠 Dashboard",
    "🔎 Browse Recipes",
    "🧾 Weekly Planner",
    "📅 Calendar",
    "🥫 Pantry",
    "💰 Pricing",
    "✏️ Edit Recipes",
    "📚 History",
]
tabs = st.tabs(tab_labels)

# ════════════════════════════════════════════════════════════════════════════
# 🏠 Dashboard
# ════════════════════════════════════════════════════════════════════════════
with tabs[0]:
    st.header("Your Cooking Dashboard")

    if recipes.empty:
        st.info(
            "👋 Welcome! Add your first recipe in the **✏️ Edit Recipes** tab."
        )
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Recipes", len(_unique_recipes(recipes)))
        rated = recipes[recipes["rating"].str.strip().ne("") & recipes["rating"].notna()]
        c2.metric("Rated", rated["recipe_name"].nunique())
        c3.metric("Weeks Tracked",
                   meal_history["week_start"].nunique() if not meal_history.empty else 0)
        c4.metric("Meals Cooked", len(meal_history))

        st.divider()

        st.subheader("🎯 Recommended for You")
        recs = _get_recommendations(5)
        if recs:
            for r in recs:
                lc, rc = st.columns([4, 1])
                lc.markdown(
                    f"**{r['recipe']}**  \n"
                    f"<small>{r['reasons']}</small>",
                    unsafe_allow_html=True,
                )
                if rc.button("➕ Plan", key=f"dash_add_{r['recipe']}"):
                    if r["recipe"] not in st.session_state["weekly_recipes"]:
                        st.session_state["weekly_recipes"].append(r["recipe"])
                    st.toast(f"Added {r['recipe']} to planner")
        else:
            st.caption("Cook some meals to get personalised recommendations.")

        st.divider()

        left, right = st.columns(2)
        with left:
            st.subheader("🏆 Top Rated")
            top = (rated.drop_duplicates("recipe_name")
                   .sort_values("rating", ascending=False).head(5))
            if not top.empty:
                for _, rw in top.iterrows():
                    st.write(f"⭐ **{rw['recipe_name']}** — {rw['rating']}/5")
            else:
                st.caption("Rate recipes to see your favourites here.")
        with right:
            st.subheader("⚡ Quick Meals (≤ 25 min)")
            quick = recipes[recipes["cook_time"].str.contains(
                r"1[0-5]|20|25", na=False, regex=True)]
            qnames = quick["recipe_name"].unique()[:5]
            for qn in qnames:
                st.write(f"⚡ **{qn}**")
            if len(qnames) == 0:
                st.caption("Add cook times to surface quick meals.")

        if st.session_state["weekly_recipes"]:
            st.divider()
            st.subheader("📋 This Week's Plan")
            for rn in st.session_state["weekly_recipes"]:
                st.write(f"• {rn}")

# ════════════════════════════════════════════════════════════════════════════
# 🔎 Browse Recipes
# ════════════════════════════════════════════════════════════════════════════
with tabs[1]:
    st.header("Browse & Search Recipes")

    if recipes.empty:
        st.info("No recipes yet — add one in **✏️ Edit Recipes**.")
    else:
        search = st.text_input("🔍 Search by recipe or ingredient:", key="browse_search")
        filt = recipes.copy()
        if search:
            mask = (
                filt["recipe_name"].str.contains(search, case=False, na=False)
                | filt["ingredient"].str.contains(search, case=False, na=False)
            )
            filt = filt[mask]

        if filt.empty:
            st.info("No recipes match your search.")
        else:
            for rname in _unique_recipes(filt):
                rdata = filt[filt["recipe_name"] == rname].iloc[0]
                cost = _recipe_cost(rname, filt)

                title = rname
                rat = rdata["rating"].strip()
                if rat:
                    title += f"  ⭐ {rat}"
                if cost > 0:
                    title += f"  💰 £{cost:.2f}"

                exp_col, btn_col = st.columns([6, 1])
                with exp_col:
                    with st.expander(title):
                        mc1, mc2, mc3 = st.columns(3)
                        ct = rdata["cook_time"]
                        if ct:
                            mc1.write(f"⏱️ {ct}")
                        if str(rdata.get("prep_friendly", "")).lower() == "true":
                            mc1.write("🍱 Meal-prep friendly")
                        if rdata["source"]:
                            mc2.write(f"📖 {rdata['source']}")
                        if rdata["source_url"]:
                            mc3.markdown(f"[🔗 Recipe link]({rdata['source_url']})")
                        if cost > 0:
                            mc3.write(f"💰 £{cost:.2f}")

                        st.dataframe(
                            filt[filt["recipe_name"] == rname][
                                ["ingredient", "quantity", "unit", "category"]
                            ],
                            hide_index=True,
                            use_container_width=True,
                        )

                        ings = filt[filt["recipe_name"] == rname]
                        missing = [
                            f"{r['ingredient']} ({r['unit']})"
                            for _, r in ings.iterrows()
                            if _lookup_price(r["ingredient"], r["unit"]) == 0
                        ]
                        if missing:
                            st.warning(
                                f"⚠️ {len(missing)} ingredient(s) missing prices: "
                                + ", ".join(missing[:5])
                                + ("…" if len(missing) > 5 else "")
                            )

                        with st.form(f"rate_form_{rname}"):
                            try:
                                idx = int(float(rat)) if rat else 0
                            except (ValueError, TypeError):
                                idx = 0
                            new_rat = st.selectbox(
                                "Rate:", ["", "1", "2", "3", "4", "5"],
                                index=idx, key=f"rate_sel_{rname}",
                            )
                            if st.form_submit_button("Save rating"):
                                recipes.loc[
                                    recipes["recipe_name"] == rname, "rating"
                                ] = new_rat
                                _save_recipes(recipes)
                                st.success("Rating saved!")

                with btn_col:
                    already = rname in st.session_state["weekly_recipes"]
                    lbl = "✅" if already else "➕"
                    if st.button(lbl, key=f"qk_{rname}",
                                 help="Toggle weekly planner"):
                        if already:
                            st.session_state["weekly_recipes"].remove(rname)
                        else:
                            st.session_state["weekly_recipes"].append(rname)
                        st.toast(f"{'Removed' if already else 'Added'} {rname}")

# ════════════════════════════════════════════════════════════════════════════
# 🧾 Weekly Planner & Shopping List
# ════════════════════════════════════════════════════════════════════════════
with tabs[2]:
    st.header("Weekly Planner & Shopping List")

    if recipes.empty:
        st.info("Add recipes first in **✏️ Edit Recipes**.")
    else:
        all_names = _unique_recipes(recipes)
        st.session_state["weekly_recipes"] = [
            r for r in st.session_state["weekly_recipes"] if r in all_names
        ]

        selected = st.multiselect(
            "Select recipes for this week:",
            options=all_names,
            default=st.session_state["weekly_recipes"],
            key="planner_select",
        )
        st.session_state["weekly_recipes"] = selected

        if selected:
            st.subheader("👥 Adjust Servings")
            cols3 = st.columns(3)
            multipliers = {}
            for i, rn in enumerate(selected):
                rd = recipes[recipes["recipe_name"] == rn].iloc[0]
                default_s = int(rd["servings"]) if pd.notna(rd["servings"]) else 2
                with cols3[i % 3]:
                    s = st.number_input(
                        rn, min_value=1, max_value=20,
                        value=st.session_state["recipe_servings"].get(rn, default_s),
                        key=f"srv_{rn}",
                    )
                    st.session_state["recipe_servings"][rn] = s
                    multipliers[rn] = s / max(default_s, 1)

            sel_df = recipes[recipes["recipe_name"].isin(selected)].copy()
            for rn, mult in multipliers.items():
                sel_df.loc[sel_df["recipe_name"] == rn, "quantity"] *= mult

            shop = (
                sel_df.groupby(["ingredient", "unit", "category"], as_index=False)
                .agg(quantity=("quantity", "sum"),
                     used_in=("recipe_name", lambda x: ", ".join(sorted(set(x)))))
                .sort_values(["category", "ingredient"])
            )

            if not pantry.empty:
                pantry_lower = set(pantry["ingredient"].str.lower())
                before = len(shop)
                shop = shop[~shop["ingredient"].str.lower().isin(pantry_lower)]
                excluded = before - len(shop)
                if excluded:
                    st.info(f"Excluded {excluded} pantry staple(s) from shopping list.")

            shop["price_per_unit"] = shop.apply(
                lambda r: _lookup_price(r["ingredient"], r["unit"]), axis=1)
            shop["item_cost"] = shop["quantity"] * shop["price_per_unit"]

            st.subheader("💰 Cost Summary")
            total_shop = shop["item_cost"].sum()
            total_meal = sum(_recipe_cost(rn, sel_df) for rn in selected)
            total_servings = sum(
                st.session_state["recipe_servings"].get(rn, 2) for rn in selected
            )

            k1, k2, k3 = st.columns(3)
            if total_meal > 0:
                k1.metric("🍽️ Total Meal Cost", f"£{total_meal:.2f}")
            if total_shop > 0:
                k2.metric("🛒 Shopping Cost", f"£{total_shop:.2f}")
            if total_meal > 0 and total_servings > 0:
                k3.metric("👤 Per Serving", f"£{total_meal / total_servings:.2f}")

            with st.expander("📊 Cost Per Recipe"):
                for rn in selected:
                    rc = _recipe_cost(rn, sel_df)
                    sv = st.session_state["recipe_servings"].get(rn, 2)
                    a, b, c = st.columns([3, 1, 1])
                    a.write(f"**{rn}**")
                    b.write(f"£{rc:.2f}")
                    c.caption(f"£{rc / max(sv, 1):.2f}/serving")

            no_price = shop[shop["price_per_unit"] == 0]
            if not no_price.empty:
                items = [f"{r['ingredient']} ({r['unit']})" for _, r in no_price.iterrows()]
                st.warning(
                    f"⚠️ {len(items)} item(s) missing pricing: "
                    + ", ".join(items[:5])
                    + ("…" if len(items) > 5 else "")
                )

            st.divider()
            st.subheader("🛒 Shopping List")

            display_shop = shop.copy()
            display_shop["price_per_unit"] = display_shop["price_per_unit"].apply(
                lambda x: f"£{x:.2f}" if x > 0 else "—")
            display_shop["item_cost"] = display_shop["item_cost"].apply(
                lambda x: f"£{x:.2f}" if x > 0 else "—")
            display_shop.columns = [
                "Ingredient", "Unit", "Category", "Qty",
                "Used In", "Price/Unit", "Total",
            ]

            st.dataframe(display_shop, hide_index=True, use_container_width=True)

            dl1, dl2 = st.columns(2)
            dl1.download_button(
                "💾 Download Shopping List",
                shop.to_csv(index=False).encode(),
                "shopping_list.csv", "text/csv",
            )

            detail_rows = []
            for rn in selected:
                rd = sel_df[sel_df["recipe_name"] == rn]
                info = rd.iloc[0]
                detail_rows.append({
                    "recipe_name": rn,
                    "servings": st.session_state["recipe_servings"].get(rn, 2),
                    "cook_time": info.get("cook_time", ""),
                    "source": info.get("source", ""),
                    "ingredient": "", "quantity": "", "unit": "", "category": "",
                })
                for _, ir in rd.iterrows():
                    detail_rows.append({
                        "recipe_name": "", "servings": "", "cook_time": "", "source": "",
                        "ingredient": ir["ingredient"],
                        "quantity": f"{ir['quantity']:.2f}" if pd.notna(ir["quantity"]) else "",
                        "unit": ir["unit"], "category": ir.get("category", ""),
                    })
            dl2.download_button(
                "📋 Download Weekly Recipes",
                pd.DataFrame(detail_rows).to_csv(index=False).encode(),
                "weekly_recipes.csv", "text/csv",
            )

            st.divider()
            st.subheader("📅 Save to Meal History")
            with st.form("save_history_form"):
                week_date = st.date_input("Week starting:", value=pd.Timestamp.now())
                if st.form_submit_button("💾 Save This Week's Meals"):
                    new_h = pd.DataFrame({
                        "week_start": [week_date.strftime("%Y-%m-%d")] * len(selected),
                        "recipe_name": selected,
                    })
                    _save_history(
                        pd.concat([meal_history, new_h], ignore_index=True)
                    )
                    st.success("Meal history saved!")
        else:
            st.info("Select recipes above to generate your shopping list.")

# ════════════════════════════════════════════════════════════════════════════
# 📅 Calendar View
# ════════════════════════════════════════════════════════════════════════════
with tabs[3]:
    st.header("📅 Weekly Meal Calendar")

    if recipes.empty:
        st.info("Add recipes first in **✏️ Edit Recipes**.")
    else:
        days = [
            "Monday", "Tuesday", "Wednesday", "Thursday",
            "Friday", "Saturday", "Sunday",
        ]
        avail = ["—"] + _unique_recipes(recipes)

        for day in days:
            c1, c2, c3 = st.columns([2, 3, 1])
            c1.markdown(f"**{day}**")
            current = st.session_state["daily_plan"].get(day)
            idx = avail.index(current) if current in avail else 0
            pick = c2.selectbox(
                day, avail, index=idx, key=f"cal_{day}",
                label_visibility="collapsed",
            )
            st.session_state["daily_plan"][day] = pick if pick != "—" else None
            if st.session_state["daily_plan"][day]:
                rd = recipes[recipes["recipe_name"] == pick]
                if not rd.empty:
                    ct = rd.iloc[0]["cook_time"]
                    if ct:
                        c3.caption(f"⏱️ {ct}")

        st.divider()
        a1, a2 = st.columns(2)
        if a1.button("📋 Add All to Weekly Planner"):
            planned = [v for v in st.session_state["daily_plan"].values() if v]
            st.session_state["weekly_recipes"] = list(
                set(st.session_state["weekly_recipes"] + planned))
            st.success(f"Added {len(planned)} recipe(s) to planner!")
        if a2.button("🗑️ Clear Calendar"):
            st.session_state["daily_plan"] = {d: None for d in days}
            st.toast("Calendar cleared")

        n_planned = sum(1 for v in st.session_state["daily_plan"].values() if v)
        if n_planned:
            st.success(f"✅ Meals planned for {n_planned}/7 days")

# ════════════════════════════════════════════════════════════════════════════
# 🥫 Pantry Staples
# ════════════════════════════════════════════════════════════════════════════
with tabs[4]:
    st.header("🥫 Pantry Staples")
    st.write("Items here are excluded from your shopping list.")

    with st.form("add_pantry_form"):
        new_staple = st.text_input("Add ingredient:")
        if st.form_submit_button("➕ Add to Pantry"):
            if new_staple.strip():
                updated = pd.concat(
                    [pantry, pd.DataFrame({"ingredient": [new_staple.strip()]})],
                    ignore_index=True,
                ).drop_duplicates()
                _save_pantry(updated)
                st.success(f"Added {new_staple.strip()}")

    if not pantry.empty:
        st.subheader("Your Pantry")
        pcols = st.columns(3)
        for i, (idx, row) in enumerate(pantry.iterrows()):
            with pcols[i % 3]:
                ic, dc = st.columns([3, 1])
                ic.write(f"• {row['ingredient']}")
                if dc.button("🗑️", key=f"dp_{idx}"):
                    _save_pantry(pantry.drop(idx).reset_index(drop=True))
                    st.toast(f"Removed {row['ingredient']}")

        st.divider()
        st.subheader("💡 Suggestions")
        common = [
            "Salt", "Pepper", "Olive oil", "Garlic", "Onion",
            "Rice", "Pasta", "Flour", "Sugar", "Butter",
        ]
        existing_lower = set(pantry["ingredient"].str.lower())
        suggestions = [c for c in common if c.lower() not in existing_lower]
        if suggestions:
            sc = st.columns(min(5, len(suggestions)))
            for j, item in enumerate(suggestions[:5]):
                if sc[j].button(f"➕ {item}", key=f"sug_{item}"):
                    _save_pantry(pd.concat(
                        [pantry, pd.DataFrame({"ingredient": [item]})],
                        ignore_index=True,
                    ))
                    st.toast(f"Added {item}")
    else:
        st.info("No pantry staples yet.")

# ════════════════════════════════════════════════════════════════════════════
# 💰 Ingredient Pricing
# ════════════════════════════════════════════════════════════════════════════
with tabs[5]:
    st.header("💰 Ingredient Pricing")

    with st.form("add_price_form"):
        st.subheader("Add / Update Price")
        pc1, pc2, pc3 = st.columns(3)
        p_name = pc1.text_input("Ingredient:")
        p_unit = pc2.text_input("Unit (g, ml, item…):")
        p_price = pc3.number_input("£ per unit:", min_value=0.0, step=0.01, format="%.4f")
        if st.form_submit_button("💾 Save Price"):
            if p_name.strip() and p_unit.strip():
                match_mask = (
                    (pricing["ingredient"].str.lower() == p_name.strip().lower())
                    & (pricing["unit"].str.lower() == p_unit.strip().lower())
                )
                updated = pricing.copy()
                if match_mask.any():
                    updated.loc[match_mask, "price_per_unit"] = p_price
                else:
                    updated = pd.concat([updated, pd.DataFrame({
                        "ingredient": [p_name.strip()],
                        "unit": [p_unit.strip()],
                        "price_per_unit": [p_price],
                        "last_updated": [""],
                    })], ignore_index=True)
                _save_pricing(updated)
                st.success("Price saved!")
            else:
                st.warning("Fill in ingredient and unit.")

    st.divider()

    if not recipes.empty:
        all_ings = recipes[["ingredient", "unit"]].drop_duplicates()
        all_ings["has_price"] = all_ings.apply(
            lambda r: _lookup_price(r["ingredient"], r["unit"]) > 0, axis=1)
        missing_p = all_ings[~all_ings["has_price"]]
        if not missing_p.empty:
            st.subheader(f"⚠️ {len(missing_p)} Ingredient(s) Missing Prices")
            for _, mr in missing_p.iterrows():
                with st.form(f"mp_{mr['ingredient']}_{mr['unit']}"):
                    a, b, c, d = st.columns([3, 2, 2, 1])
                    a.write(f"**{mr['ingredient']}**")
                    b.write(mr["unit"])
                    mp = c.number_input(
                        "£", min_value=0.0, step=0.01, format="%.4f",
                        key=f"mpv_{mr['ingredient']}_{mr['unit']}",
                    )
                    if d.form_submit_button("💾"):
                        up = pd.concat([pricing, pd.DataFrame({
                            "ingredient": [mr["ingredient"]],
                            "unit": [mr["unit"]],
                            "price_per_unit": [mp],
                            "last_updated": [""],
                        })], ignore_index=True)
                        _save_pricing(up)
                        st.success(f"Saved {mr['ingredient']}")
        else:
            st.success("✅ All ingredients have pricing!")

    st.divider()

    st.subheader("📋 All Prices")
    if not pricing.empty:
        disp_p = pricing.copy().sort_values("ingredient")
        if "last_updated" in disp_p.columns:
            disp_p["last_updated"] = (
                pd.to_datetime(disp_p["last_updated"], errors="coerce")
                .dt.strftime("%Y-%m-%d %H:%M")
                .fillna("")
            )

        edited_prices = st.data_editor(
            disp_p, hide_index=True, use_container_width=True,
            column_config={
                "ingredient": st.column_config.TextColumn("Ingredient"),
                "unit": st.column_config.TextColumn("Unit"),
                "price_per_unit": st.column_config.NumberColumn(
                    "£/unit", format="£%.4f"),
                "last_updated": st.column_config.TextColumn("Updated"),
            },
            disabled=["last_updated"],
        )
        if st.button("💾 Save All Price Changes"):
            _save_pricing(edited_prices)
            st.success("All prices saved!")

        st.download_button(
            "📥 Download Pricing CSV",
            pricing.to_csv(index=False).encode(),
            "ingredient_pricing.csv", "text/csv",
        )
    else:
        st.info("No prices yet — add some above.")

    st.divider()

    st.subheader("📊 Price Change History")
    ph = _load_price_history()
    if not ph.empty:
        hs = st.text_input("🔍 Search history:", key="ph_search")
        disp_h = ph.copy()
        disp_h["changed_at"] = (
            pd.to_datetime(disp_h["changed_at"], errors="coerce")
            .dt.strftime("%Y-%m-%d %H:%M")
            .fillna("")
        )
        disp_h = disp_h.sort_values("changed_at", ascending=False)
        if hs:
            disp_h = disp_h[
                disp_h["ingredient"].str.contains(hs, case=False, na=False)
            ]

        if disp_h.empty:
            st.info("No matching history.")
        else:
            disp_h["change"] = disp_h.apply(
                lambda r: (
                    f"{((r['new_price'] - r['old_price']) / r['old_price'] * 100):.1f}%"
                    if r["old_price"] > 0 else "New"
                ),
                axis=1,
            )
            disp_h["old_price"] = disp_h["old_price"].apply(lambda x: f"£{x:.4f}")
            disp_h["new_price"] = disp_h["new_price"].apply(lambda x: f"£{x:.4f}")
            disp_h.columns = ["Ingredient", "Unit", "Old", "New", "Changed At", "Δ"]
            st.dataframe(
                disp_h[["Ingredient", "Unit", "Old", "New", "Δ", "Changed At"]],
                hide_index=True, use_container_width=True,
            )
            st.caption(f"{len(disp_h)} change(s)")
    else:
        st.info("No price changes recorded yet.")

# ════════════════════════════════════════════════════════════════════════════
# ✏️ Edit Recipes
# ════════════════════════════════════════════════════════════════════════════
with tabs[6]:
    st.header("Add or Edit Recipes")

    with st.expander("➕ Add New Recipe", expanded=not bool(_unique_recipes(recipes))):
        with st.form("new_recipe_form"):
            nc1, nc2 = st.columns([3, 1])
            nr_name = nc1.text_input(
                "Recipe name *", placeholder="e.g. Spaghetti Carbonara")
            nr_servings = nc2.number_input("Servings *", 1, 20, 2)

            mc1, mc2 = st.columns(2)
            with mc1:
                nr_cook = st.text_input("Cook time", placeholder="e.g. 30 mins")
                nr_rating = st.selectbox(
                    "Rating", [""] + [str(i) for i in range(1, 6)])
                nr_prep = st.checkbox("Meal prep friendly?")
            with mc2:
                nr_source = st.text_input(
                    "Source", placeholder="e.g. BBC Good Food")
                nr_url = st.text_input("Source URL", placeholder="https://…")
            nr_tags = st.text_input(
                "Tags (comma-separated)", placeholder="Italian, Pasta, Quick")
            nr_notes = st.text_area("Notes", placeholder="Special instructions…")

            st.divider()
            st.markdown(
                "**Ingredients** — one per line: "
                "`name, quantity, unit, category` (category optional)"
            )
            nr_ings = st.text_area(
                "Ingredients *",
                placeholder=(
                    "Chicken breast, 300, g, Protein\n"
                    "Onion, 1, item, Vegetables"
                ),
                height=200,
            )

            if st.form_submit_button("💾 Save Recipe", type="primary"):
                if not nr_name.strip():
                    st.error("Please enter a recipe name.")
                elif not nr_ings.strip():
                    st.error("Please enter at least one ingredient.")
                else:
                    rid = str(uuid.uuid4())
                    rows, errors = [], []
                    for line in nr_ings.strip().splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        parts = [p.strip() for p in line.split(",")]
                        try:
                            if len(parts) == 4:
                                ing, qty, unit, cat = parts
                            elif len(parts) == 3:
                                ing, qty, unit = parts
                                cat = ""
                            else:
                                errors.append(f"Bad format: {line}")
                                continue
                            rows.append({
                                "recipe_id": rid,
                                "recipe_name": nr_name.strip(),
                                "ingredient": ing,
                                "quantity": float(qty),
                                "unit": unit,
                                "category": cat,
                                "tags": nr_tags,
                                "cook_time": nr_cook,
                                "rating": nr_rating,
                                "source": nr_source,
                                "source_url": nr_url,
                                "servings": nr_servings,
                                "notes": nr_notes,
                                "estimated_cost": 0.0,
                                "prep_friendly": nr_prep,
                            })
                        except ValueError as e:
                            errors.append(f"Parse error on '{line}': {e}")
                    for err in errors:
                        st.error(err)
                    if rows:
                        _save_recipes(pd.concat(
                            [recipes, pd.DataFrame(rows)], ignore_index=True))
                        st.success(
                            f"✅ **{nr_name}** saved with {len(rows)} ingredient(s)!"
                        )

    st.subheader("✏️ Edit Recipe Metadata")
    names = _unique_recipes(recipes)
    pick_edit = st.selectbox("Select recipe:", [""] + names, key="edit_pick")
    if pick_edit:
        rd = recipes[recipes["recipe_name"] == pick_edit].iloc[0]
        with st.form(f"edit_meta_{pick_edit}"):
            en = st.text_input("Name", value=pick_edit)
            e1, e2, e3 = st.columns(3)
            with e1:
                ec = st.text_input("Cook Time", value=rd["cook_time"])
                es = st.number_input(
                    "Servings", 1, 20,
                    int(rd["servings"]) if pd.notna(rd["servings"]) else 2,
                )
            with e2:
                try:
                    ri = int(float(rd["rating"])) if rd["rating"].strip() else 0
                except (ValueError, TypeError):
                    ri = 0
                er = st.selectbox(
                    "Rating", [""] + [str(i) for i in range(1, 6)], index=ri)
                esrc = st.text_input("Source", value=rd["source"])
            with e3:
                et = st.text_input("Tags", value=rd["tags"])
                eu = st.text_input("Source URL", value=rd["source_url"])
            enotes = st.text_area("Notes", value=rd["notes"])

            sc_btn, dc_btn, dupc_btn = st.columns(3)
            save_btn = sc_btn.form_submit_button("💾 Save", type="primary")
            del_btn = dc_btn.form_submit_button("🗑️ Delete")
            dup_btn = dupc_btn.form_submit_button("📋 Duplicate")

            if save_btn:
                updated = recipes.copy()
                updated.loc[updated["recipe_name"] == pick_edit, "recipe_name"] = en
                for col, val in [
                    ("cook_time", ec), ("rating", er), ("source", esrc),
                    ("source_url", eu), ("tags", et), ("servings", es),
                    ("notes", enotes),
                ]:
                    updated.loc[updated["recipe_name"] == en, col] = val
                _save_recipes(updated)
                st.success("Saved!")
            elif del_btn:
                _save_recipes(recipes[recipes["recipe_name"] != pick_edit])
                st.success(f"Deleted {pick_edit}")
            elif dup_btn:
                dupe = recipes[recipes["recipe_name"] == pick_edit].copy()
                dupe["recipe_id"] = str(uuid.uuid4())
                dupe["recipe_name"] = f"{pick_edit} (Copy)"
                _save_recipes(pd.concat([recipes, dupe], ignore_index=True))
                st.success(f"Duplicated as '{pick_edit} (Copy)'")

    st.subheader("🧩 Edit Individual Ingredients")
    if recipes.empty:
        st.info("No recipes yet.")
    else:
        filt_name = st.selectbox(
            "Filter by recipe:",
            ["All recipes"] + names,
            key="ing_filter",
        )
        if filt_name == "All recipes":
            to_edit = recipes
        else:
            to_edit = recipes[recipes["recipe_name"] == filt_name]

        edited_ings = st.data_editor(
            to_edit, num_rows="dynamic", use_container_width=True,
            key="ing_editor",
        )
        st.caption(f"Showing {len(to_edit)} row(s)")

        if st.button("💾 Save Ingredient Changes"):
            if filt_name == "All recipes":
                _save_recipes(edited_ings)
            else:
                full = recipes.copy()
                full = full[full["recipe_name"] != filt_name]
                full = pd.concat([full, edited_ings], ignore_index=True)
                _save_recipes(full)
            st.success("Ingredient changes saved!")

# ════════════════════════════════════════════════════════════════════════════
# 📚 Meal History
# ════════════════════════════════════════════════════════════════════════════
with tabs[7]:
    st.header("📚 Meal History")

    if meal_history.empty:
        st.info(
            "No history yet — save a weekly plan from the planner!"
        )
    else:
        search_h = st.text_input("🔍 Search history:", key="hist_search")
        disp_hist = meal_history.copy()
        disp_hist["week_start"] = pd.to_datetime(
            disp_hist["week_start"], errors="coerce")
        disp_hist = disp_hist.sort_values("week_start", ascending=False)
        if search_h:
            disp_hist = disp_hist[
                disp_hist["recipe_name"].str.contains(
                    search_h, case=False, na=False)
                | disp_hist["week_start"].astype(str).str.contains(
                    search_h, case=False, na=False)
            ]

        if disp_hist.empty:
            st.info("No matching history.")
        else:
            for ws in disp_hist["week_start"].unique():
                wk = disp_hist[disp_hist["week_start"] == ws]
                label = pd.to_datetime(ws).strftime("%B %d, %Y")
                with st.expander(
                    f"📅 Week of {label} ({len(wk)} recipes)"
                ):
                    for idx, row in wk.iterrows():
                        c1, c2 = st.columns([4, 1])
                        c1.write(f"• {row['recipe_name']}")
                        if c2.button("🗑️", key=f"dh_{idx}"):
                            _save_history(
                                meal_history.drop(idx).reset_index(drop=True))
                            st.toast("Entry removed")

        st.divider()
        st.subheader("📊 Statistics")
        s1, s2, s3 = st.columns(3)
        s1.metric("Weeks Tracked", disp_hist["week_start"].nunique())
        s2.metric("Total Meals", len(disp_hist))
        s3.metric("Unique Recipes", disp_hist["recipe_name"].nunique())

        if len(disp_hist) > 0:
            st.subheader("⭐ Most Cooked")
            for name, count in (
                disp_hist["recipe_name"].value_counts().head(5).items()
            ):
                st.write(f"**{name}**: {count}×")

        st.download_button(
            "💾 Download History CSV",
            meal_history.to_csv(index=False).encode(),
            "meal_history.csv", "text/csv",
        )

        with st.form("clear_history_form"):
            st.warning("This will permanently delete all meal history.")
            if st.form_submit_button("🗑️ Clear All History"):
                _save_history(
                    pd.DataFrame(columns=["week_start", "recipe_name"]))
                st.success("History cleared.")
