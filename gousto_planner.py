import streamlit as st
import pandas as pd
import uuid
import os

DATA_FILE = "recipes.csv"

# --- Load and save ---
@st.cache_data
def load_data():
    if os.path.exists(DATA_FILE):
        df = pd.read_csv(DATA_FILE)
    else:
        df = pd.DataFrame(columns=["recipe_id", "recipe_name", "ingredient", "quantity", "unit", "category", "tags"])
    return df

def save_data(df):
    df.to_csv(DATA_FILE, index=False)
    st.success("✅ Recipe data saved!")

recipes = load_data()

st.set_page_config(page_title="Gousto Recipe Manager", layout="wide")
st.title("🥘 Gousto Recipe Manager")

# --- Tabs for better navigation ---
tabs = st.tabs(["🔎 Browse Recipes", "🧾 Weekly Planner", "✏️ Edit Recipes"])

# ============================================================
# 🔎 TAB 1: Browse & Search
# ============================================================
with tabs[0]:
    st.header("Browse & Search Recipes")
    search_term = st.text_input("Search by recipe or ingredient:")

    if search_term:
        filtered = recipes[
            recipes["recipe_name"].str.contains(search_term, case=False, na=False)
            | recipes["ingredient"].str.contains(search_term, case=False, na=False)
        ]
    else:
        filtered = recipes.copy()

    if filtered.empty:
        st.info("No recipes match your search.")
    else:
        for recipe in sorted(filtered["recipe_name"].unique()):
            with st.expander(recipe):
                st.dataframe(
                    filtered[filtered["recipe_name"] == recipe][["ingredient", "quantity", "unit", "category"]],
                    hide_index=True,
                )

# ============================================================
# 🧾 TAB 2: Weekly Planner
# ============================================================
with tabs[1]:
    st.header("Weekly Planner & Shopping List")

    recipe_names = sorted(recipes["recipe_name"].unique())
    selected_recipes = st.multiselect(
        "Select recipes for your week:",
        options=recipe_names
    )

    if selected_recipes:
        shopping_list = (
            recipes[recipes["recipe_name"].isin(selected_recipes)]
            .groupby(["ingredient", "unit", "category"], as_index=False)
            .agg({"quantity": "sum"})
            .sort_values(by=["category", "ingredient"])
        )

        st.subheader("🛒 Combined Shopping List")
        st.dataframe(shopping_list, hide_index=True)

        csv = shopping_list.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="💾 Download Shopping List (CSV)",
            data=csv,
            file_name="shopping_list.csv",
            mime="text/csv"
        )
    else:
        st.info("👈 Choose some recipes to generate your shopping list.")

# ============================================================
# ✏️ TAB 3: Add / Edit Recipes
# ============================================================
with tabs[2]:
    st.header("Add or Modify Recipes")

    with st.expander("➕ Add New Recipe"):
        new_recipe_name = st.text_input("Recipe name")
        new_tags = st.text_input("Tags (comma-separated)")
        new_ingredients = st.text_area("Ingredients (one per line, e.g. 'Chicken breast,300,g,Protein')")

        if st.button("Add Recipe"):
            if new_recipe_name and new_ingredients:
                new_rows = []
                for line in new_ingredients.strip().split("\n"):
                    try:
                        ing, qty, unit, cat = [x.strip() for x in line.split(",")]
                        new_rows.append({
                            "recipe_id": str(uuid.uuid4()),
                            "recipe_name": new_recipe_name,
                            "ingredient": ing,
                            "quantity": float(qty),
                            "unit": unit,
                            "category": cat,
                            "tags": new_tags
                        })
                    except ValueError:
                        st.error(f"Invalid line format: {line}")
                if new_rows:
                    new_df = pd.DataFrame(new_rows)
                    updated = pd.concat([recipes, new_df], ignore_index=True)
                    save_data(updated)
                    st.rerun()
            else:
                st.warning("Please fill in the recipe name and ingredients.")

    st.subheader("🧩 Existing Recipes")
    editable = st.data_editor(recipes, num_rows="dynamic", use_container_width=True)
    if st.button("💾 Save Changes"):
        save_data(editable)
        st.rerun()
