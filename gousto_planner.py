import streamlit as st
import pandas as pd

# --- Load recipe data ---
@st.cache_data
def load_recipes():
    df = pd.read_csv("recipes.csv")
    return df

recipes = load_recipes()

st.title("🥘 Weekly Recipe Planner & Shopping List")

# --- Sidebar recipe selection ---
recipe_names = sorted(recipes["recipe_name"].unique())
selected_recipes = st.sidebar.multiselect(
    "Select your recipes for this week:",
    options=recipe_names,
    default=[]
)

if selected_recipes:
    st.subheader("🧾 Selected Recipes")
    st.write(", ".join(selected_recipes))

    # --- Generate combined shopping list ---
    shopping_list = (
        recipes[recipes["recipe_name"].isin(selected_recipes)]
        .groupby(["ingredient", "unit", "category"], as_index=False)
        .agg({"quantity": "sum"})
        .sort_values(by=["category", "ingredient"])
    )

    # --- Display ---
    st.subheader("🛒 Shopping List")
    st.dataframe(shopping_list, hide_index=True)

    # --- Export to CSV ---
    csv = shopping_list.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="💾 Download Shopping List (CSV)",
        data=csv,
        file_name="shopping_list.csv",
        mime="text/csv"
    )
else:
    st.info("👈 Select one or more recipes to build your shopping list.")

# --- Optional: Show recipe details ---
with st.expander("📖 View All Recipes"):
    st.dataframe(recipes)
