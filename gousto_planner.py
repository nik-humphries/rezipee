import streamlit as st
import pandas as pd
import uuid
import os

DATA_FILE = "recipes.csv"
HISTORY_FILE = "meal_history.csv"
PANTRY_FILE = "pantry_staples.csv"

# --- Load and save ---
@st.cache_data
def load_data():
    if os.path.exists(DATA_FILE):
        df = pd.read_csv(DATA_FILE)
        # Ensure quantity is numeric
        df['quantity'] = pd.to_numeric(df['quantity'], errors='coerce')
        # Fill NaN values in new columns
        for col in ['rating', 'source', 'source_url', 'servings', 'notes', 'estimated_cost', 'prep_friendly']:
            if col not in df.columns:
                if col == 'servings':
                    df[col] = 2
                elif col == 'estimated_cost':
                    df[col] = 0.0
                elif col == 'prep_friendly':
                    df[col] = False
                else:
                    df[col] = ''
        # Ensure servings has a default
        df['servings'] = df['servings'].fillna(2)
        df['estimated_cost'] = pd.to_numeric(df['estimated_cost'], errors='coerce').fillna(0.0)
    else:
        df = pd.DataFrame(columns=["recipe_id", "recipe_name", "ingredient", "quantity", "unit", "category", "tags", "cook_time", "rating", "source", "source_url", "servings", "notes", "estimated_cost", "prep_friendly"])
    return df

def save_data(df):
    df.to_csv(DATA_FILE, index=False)
    load_data.clear()  # Clear cache to reload fresh data
    st.success("✅ Recipe data saved!")

def load_history():
    if os.path.exists(HISTORY_FILE):
        df = pd.read_csv(HISTORY_FILE)
        if 'week_start' in df.columns:
            df['week_start'] = pd.to_datetime(df['week_start'])
        return df
    else:
        return pd.DataFrame(columns=["week_start", "recipe_name"])

def save_history(df):
    df.to_csv(HISTORY_FILE, index=False)
    st.success("✅ Meal history saved!")

def load_pantry():
    if os.path.exists(PANTRY_FILE):
        return pd.read_csv(PANTRY_FILE)
    else:
        return pd.DataFrame(columns=["ingredient"])

def save_pantry(df):
    df.to_csv(PANTRY_FILE, index=False)
    st.success("✅ Pantry staples saved!")

def get_recipe_recommendations(recipes_df, history_df, top_n=5):
    """Generate smart recipe recommendations"""
    recipe_names = recipes_df["recipe_name"].unique()
    recommendations = []
    
    for recipe in recipe_names:
        recipe_data = recipes_df[recipes_df["recipe_name"] == recipe].iloc[0]
        score = 0
        reasons = []
        
        # Rating boost
        rating = recipe_data.get('rating', '')
        if rating and str(rating).strip() and rating != '':
            try:
                rating_val = float(rating)
                score += rating_val * 10
                if rating_val >= 4:
                    reasons.append(f"⭐ Rated {rating_val}/5")
            except:
                pass
        
        # Check cooking history
        if not history_df.empty:
            times_cooked = len(history_df[history_df['recipe_name'] == recipe])
            if times_cooked > 0:
                last_cooked = history_df[history_df['recipe_name'] == recipe]['week_start'].max()
                days_since = (pd.Timestamp.now() - last_cooked).days
                
                if days_since > 60:
                    score += 15
                    reasons.append(f"🕐 Not cooked in {days_since} days")
                elif days_since < 14:
                    score -= 20  # Cooked recently, lower priority
                
                if times_cooked >= 3:
                    reasons.append(f"❤️ Favorite (cooked {times_cooked}x)")
                    score += 5
            else:
                score += 10
                reasons.append("✨ Never tried")
        else:
            score += 10
            reasons.append("✨ Never tried")
        
        # Quick meals boost
        cook_time = str(recipe_data.get('cook_time', ''))
        if '15' in cook_time or '20' in cook_time:
            score += 5
            reasons.append("⚡ Quick meal")
        
        recommendations.append({
            'recipe': recipe,
            'score': score,
            'reasons': ' • '.join(reasons) if reasons else 'Good choice!'
        })
    
    return sorted(recommendations, key=lambda x: x['score'], reverse=True)[:top_n]

recipes = load_data()
meal_history = load_history()
pantry_staples = load_pantry()

# Initialize session state for weekly planner
if "weekly_recipes" not in st.session_state:
    st.session_state.weekly_recipes = []
if "daily_plan" not in st.session_state:
    st.session_state.daily_plan = {day: None for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]}

st.set_page_config(page_title="Gousto Recipe Manager", layout="wide")
st.title("🥘 Gousto Recipe Manager")

# --- Tabs for better navigation ---
tabs = st.tabs(["🏠 Dashboard", "🔎 Browse Recipes", "🧾 Weekly Planner", "📅 Calendar View", "🥫 Pantry", "✏️ Edit Recipes", "📚 Meal History"])

# ============================================================
# 🏠 TAB 0: Dashboard
# ============================================================
with tabs[0]:
    st.header("� Your Cooking Dashboard")
    
    # Key metrics
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        total_recipes = len(recipes["recipe_name"].unique())
        st.metric("Total Recipes", total_recipes)
    
    with col2:
        rated_recipes = len(recipes[recipes['rating'].notna() & (recipes['rating'] != '')]["recipe_name"].unique())
        st.metric("Rated Recipes", rated_recipes)
    
    with col3:
        if not meal_history.empty:
            weeks_tracked = meal_history['week_start'].nunique()
            st.metric("Weeks Tracked", weeks_tracked)
        else:
            st.metric("Weeks Tracked", 0)
    
    with col4:
        if not meal_history.empty:
            total_meals = len(meal_history)
            st.metric("Meals Cooked", total_meals)
        else:
            st.metric("Meals Cooked", 0)
    
    st.divider()
    
    # Smart Recommendations
    st.subheader("🎯 Recommended for You")
    recommendations = get_recipe_recommendations(recipes, meal_history, top_n=5)
    
    if recommendations:
        for rec in recommendations:
            col_name, col_btn = st.columns([3, 1])
            with col_name:
                st.write(f"**{rec['recipe']}**")
                st.caption(rec['reasons'])
            with col_btn:
                if st.button("Add to Plan", key=f"rec_{rec['recipe']}"):
                    if rec['recipe'] not in st.session_state.weekly_recipes:
                        st.session_state.weekly_recipes.append(rec['recipe'])
                        st.success("Added!")
                        st.rerun()
    else:
        st.info("Add some recipes and start cooking to get personalized recommendations!")
    
    st.divider()
    
    # Quick insights
    col_insights1, col_insights2 = st.columns(2)
    
    with col_insights1:
        st.subheader("🏆 Top Rated Recipes")
        rated = recipes[recipes['rating'].notna() & (recipes['rating'] != '') & (recipes['rating'] != '0')]
        if not rated.empty:
            rated_unique = rated.drop_duplicates('recipe_name').sort_values('rating', ascending=False).head(5)
            for _, recipe in rated_unique.iterrows():
                st.write(f"⭐ **{recipe['recipe_name']}** - {recipe['rating']}/5")
        else:
            st.info("Rate some recipes to see your favorites!")
    
    with col_insights2:
        st.subheader("⚡ Quick Meals (≤ 25 min)")
        quick_meals = recipes[recipes['cook_time'].str.contains('15|20|25', na=False, case=False)]
        quick_names = quick_meals['recipe_name'].unique()[:5]
        if len(quick_names) > 0:
            for recipe in quick_names:
                st.write(f"⚡ **{recipe}**")
        else:
            st.info("No quick meals found. Add cook times to your recipes!")
    
    st.divider()
    
    # Weekly plan overview
    if st.session_state.weekly_recipes:
        st.subheader("📋 This Week's Plan")
        st.write(f"You have **{len(st.session_state.weekly_recipes)}** recipes planned:")
        for recipe in st.session_state.weekly_recipes:
            st.write(f"• {recipe}")
    else:
        st.info("👈 No recipes planned yet. Go to Weekly Planner to get started!")

# ============================================================
# �🔎 TAB 1: Browse & Search
# ============================================================
with tabs[1]:
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
            recipe_data = filtered[filtered["recipe_name"] == recipe].iloc[0]
            
            # Get current rating
            current_rating = recipe_data.get('rating', '')
            current_rating = '' if pd.isna(current_rating) else str(current_rating)
            
            # Build expander title with rating
            title = recipe
            if current_rating and current_rating.strip():
                title += f" ⭐ {current_rating}"
            
            # Quick add button before expander
            col_title, col_quick_add = st.columns([5, 1])
            with col_title:
                expander_label = title
            with col_quick_add:
                if st.button("➕ Add", key=f"quick_add_{recipe}"):
                    if recipe not in st.session_state.weekly_recipes:
                        st.session_state.weekly_recipes.append(recipe)
                        st.success(f"✅ Added!")
                        st.rerun()
                    else:
                        st.info(f"Already added!")
            
            with st.expander(title):
                # Show recipe metadata
                col1, col2, col3 = st.columns(3)
                with col1:
                    if recipe_data.get('cook_time'):
                        st.write(f"⏱️ **Cook time:** {recipe_data['cook_time']}")
                    # Show prep-friendly indicator
                    if recipe_data.get('prep_friendly'):
                        st.write("🍱 **Meal prep friendly**")
                with col2:
                    if recipe_data.get('source'):
                        st.write(f"📖 **Source:** {recipe_data['source']}")
                with col3:
                    if recipe_data.get('source_url'):
                        st.markdown(f"🔗 [Recipe Link]({recipe_data['source_url']})")
                    if recipe_data.get('estimated_cost') and float(recipe_data.get('estimated_cost', 0)) > 0:
                        st.write(f"💰 **Cost:** £{float(recipe_data['estimated_cost']):.2f}")
                
                # Show ingredients
                st.dataframe(
                    filtered[filtered["recipe_name"] == recipe][["ingredient", "quantity", "unit", "category"]],
                    hide_index=True,
                )
                
                # Rating interface
                col_rate, col_add = st.columns(2)
                with col_rate:
                    # Fix rating index calculation
                    rating_value = recipe_data.get('rating', '')
                    if pd.isna(rating_value) or rating_value == '' or str(rating_value).strip() == '':
                        rating_index = 0
                    else:
                        try:
                            rating_index = int(float(rating_value))
                        except (ValueError, TypeError):
                            rating_index = 0
                    
                    new_rating = st.selectbox(
                        "Rate this recipe:",
                        ["", "1", "2", "3", "4", "5"],
                        index=rating_index,
                        key=f"rate_{recipe}"
                    )
                    if st.button("Save Rating", key=f"save_rating_{recipe}"):
                        # Update rating for all ingredients in this recipe
                        recipes.loc[recipes["recipe_name"] == recipe, "rating"] = new_rating if new_rating else ''
                        save_data(recipes)
                        st.rerun()
                
                # Show if already in weekly planner
                with col_add:
                    if recipe in st.session_state.weekly_recipes:
                        st.success("✅ In weekly plan")

# ============================================================
# 🧾 TAB 2: Weekly Planner
# ============================================================
with tabs[2]:
    st.header("Weekly Planner & Shopping List")

    recipe_names = sorted(recipes["recipe_name"].unique())
    
    # Pre-populate with session state recipes
    if st.session_state.weekly_recipes:
        # Filter to only include recipes that still exist in the data
        st.session_state.weekly_recipes = [r for r in st.session_state.weekly_recipes if r in recipe_names]
    
    selected_recipes = st.multiselect(
        "Select recipes for your week:",
        options=recipe_names,
        default=st.session_state.weekly_recipes
    )
    
    # Update session state when selection changes
    st.session_state.weekly_recipes = selected_recipes

    if selected_recipes:
        # Servings adjustment
        st.subheader("👥 Adjust Servings")
        st.write("Adjust the number of servings for your recipes (default is based on each recipe's serving size):")
        
        # Initialize servings state
        if "recipe_servings" not in st.session_state:
            st.session_state.recipe_servings = {}
        
        servings_col1, servings_col2, servings_col3 = st.columns(3)
        servings_multipliers = {}
        
        for idx, recipe in enumerate(selected_recipes):
            recipe_data = recipes[recipes["recipe_name"] == recipe].iloc[0]
            default_servings = int(recipe_data.get('servings', 2))
            
            col = [servings_col1, servings_col2, servings_col3][idx % 3]
            with col:
                servings = st.number_input(
                    f"{recipe}",
                    min_value=1,
                    max_value=20,
                    value=st.session_state.recipe_servings.get(recipe, default_servings),
                    key=f"servings_{recipe}"
                )
                st.session_state.recipe_servings[recipe] = servings
                servings_multipliers[recipe] = servings / default_servings
        
        # Scale quantities based on servings
        selected_data = recipes[recipes["recipe_name"].isin(selected_recipes)].copy()
        for recipe, multiplier in servings_multipliers.items():
            selected_data.loc[selected_data["recipe_name"] == recipe, "quantity"] *= multiplier
        
        shopping_list = (
            selected_data
            .groupby(["ingredient", "unit", "category"], as_index=False)
            .agg({
                "quantity": "sum",
                "recipe_name": lambda x: ", ".join(sorted(set(x)))
            })
            .sort_values(by=["category", "ingredient"])
            .rename(columns={"recipe_name": "used_in_recipes"})
        )
        
        # Exclude pantry staples
        if not pantry_staples.empty:
            pantry_list = pantry_staples['ingredient'].str.lower().tolist()
            shopping_list = shopping_list[~shopping_list['ingredient'].str.lower().isin(pantry_list)]
            
            excluded_count = len(selected_data) - len(shopping_list)
            if excluded_count > 0:
                st.info(f"ℹ️ Excluded {excluded_count} pantry staples from shopping list")
        
        # Reorder columns for better display
        shopping_list = shopping_list[["category", "ingredient", "quantity", "unit", "used_in_recipes"]]

        st.subheader("🛒 Combined Shopping List")
        
        # Calculate estimated cost
        total_cost = 0
        for recipe in selected_recipes:
            recipe_cost = recipes[recipes["recipe_name"] == recipe].iloc[0].get('estimated_cost', 0)
            if pd.notna(recipe_cost) and recipe_cost:
                servings_multiplier = st.session_state.recipe_servings.get(recipe, 2) / recipes[recipes["recipe_name"] == recipe].iloc[0].get('servings', 2)
                total_cost += float(recipe_cost) * servings_multiplier
        
        if total_cost > 0:
            st.metric("💰 Estimated Weekly Cost", f"£{total_cost:.2f}")
        
        st.dataframe(shopping_list, hide_index=True)

        col1, col2 = st.columns(2)
        
        with col1:
            csv = shopping_list.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="💾 Download Shopping List (CSV)",
                data=csv,
                file_name="shopping_list.csv",
                mime="text/csv"
            )
        
        with col2:
            # Export detailed weekly recipe list with ingredients
            recipe_details_list = []
            for recipe in selected_recipes:
                recipe_data = selected_data[selected_data["recipe_name"] == recipe]
                recipe_info = recipe_data.iloc[0]
                servings = st.session_state.recipe_servings.get(recipe, int(recipe_info.get('servings', 2)))
                
                # Add recipe header
                recipe_details_list.append({
                    "recipe_name": recipe,
                    "servings": servings,
                    "cook_time": recipe_info.get('cook_time', ''),
                    "source": recipe_info.get('source', ''),
                    "source_url": recipe_info.get('source_url', ''),
                    "ingredient": "--- RECIPE DETAILS ---",
                    "quantity": "",
                    "unit": "",
                    "category": ""
                })
                
                # Add ingredients
                for _, ing_row in recipe_data.iterrows():
                    recipe_details_list.append({
                        "recipe_name": "",
                        "servings": "",
                        "cook_time": "",
                        "source": "",
                        "source_url": "",
                        "ingredient": ing_row['ingredient'],
                        "quantity": f"{ing_row['quantity']:.2f}" if pd.notna(ing_row['quantity']) else "",
                        "unit": ing_row['unit'],
                        "category": ing_row.get('category', '')
                    })
                
                # Add separator
                recipe_details_list.append({
                    "recipe_name": "",
                    "servings": "",
                    "cook_time": "",
                    "source": "",
                    "source_url": "",
                    "ingredient": "",
                    "quantity": "",
                    "unit": "",
                    "category": ""
                })
            
            recipe_list_df = pd.DataFrame(recipe_details_list)
            recipe_csv = recipe_list_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="📋 Download Weekly Recipe List (CSV)",
                data=recipe_csv,
                file_name="weekly_recipes.csv",
                mime="text/csv"
            )
        
        # Save to meal history
        st.subheader("📅 Save to Meal History")
        week_date = st.date_input("Week starting:", value=pd.Timestamp.now())
        if st.button("💾 Save This Week's Meals to History"):
            new_history = pd.DataFrame({
                "week_start": [week_date.strftime("%Y-%m-%d")] * len(selected_recipes),
                "recipe_name": selected_recipes
            })
            updated_history = pd.concat([meal_history, new_history], ignore_index=True)
            save_history(updated_history)
            st.rerun()
    else:
        st.info("👈 Choose some recipes to generate your shopping list.")

# ============================================================
# 📅 TAB 3: Calendar View
# ============================================================
with tabs[3]:
    st.header("📅 Weekly Meal Calendar")
    
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    
    st.write("Plan which recipe you'll cook on each day of the week:")
    
    for day in days:
        col1, col2, col3 = st.columns([2, 3, 1])
        
        with col1:
            st.write(f"**{day}**")
        
        with col2:
            available_recipes = ["None"] + sorted(recipes["recipe_name"].unique().tolist())
            current_selection = st.session_state.daily_plan.get(day, "None")
            if current_selection not in available_recipes:
                current_selection = "None"
            
            selected = st.selectbox(
                f"{day}",
                available_recipes,
                index=available_recipes.index(current_selection),
                key=f"day_{day}",
                label_visibility="collapsed"
            )
            st.session_state.daily_plan[day] = selected if selected != "None" else None
        
        with col3:
            if st.session_state.daily_plan[day]:
                recipe_info = recipes[recipes["recipe_name"] == st.session_state.daily_plan[day]].iloc[0]
                if recipe_info.get('cook_time'):
                    st.caption(f"⏱️ {recipe_info['cook_time']}")
    
    st.divider()
    
    # Quick actions
    col_action1, col_action2 = st.columns(2)
    
    with col_action1:
        if st.button("📋 Add All to Weekly Planner"):
            planned_recipes = [meal for meal in st.session_state.daily_plan.values() if meal]
            st.session_state.weekly_recipes = list(set(st.session_state.weekly_recipes + planned_recipes))
            st.success(f"Added {len(planned_recipes)} recipes to weekly planner!")
    
    with col_action2:
        if st.button("🗑️ Clear Calendar"):
            st.session_state.daily_plan = {day: None for day in days}
            st.rerun()
    
    # Summary
    planned_days = sum(1 for meal in st.session_state.daily_plan.values() if meal)
    if planned_days > 0:
        st.success(f"✅ You have meals planned for {planned_days} days this week!")
    else:
        st.info("Start planning your week by selecting recipes for each day!")

# ============================================================
# 🥫 TAB 4: Pantry Staples
# ============================================================
with tabs[4]:
    st.header("🥫 Pantry Staples Manager")
    
    st.write("Track ingredients you always have at home. These will be excluded from your shopping list!")
    
    # Add pantry staple
    with st.form("add_pantry"):
        new_staple = st.text_input("Add ingredient to pantry:")
        if st.form_submit_button("➕ Add to Pantry"):
            if new_staple:
                new_df = pd.DataFrame({"ingredient": [new_staple.strip()]})
                updated_pantry = pd.concat([pantry_staples, new_df], ignore_index=True)
                updated_pantry = updated_pantry.drop_duplicates()
                save_pantry(updated_pantry)
                st.rerun()
    
    st.divider()
    
    # Display and manage pantry
    if not pantry_staples.empty:
        st.subheader("Your Pantry Staples")
        
        # Show in columns
        num_cols = 3
        cols = st.columns(num_cols)
        
        for idx, staple in pantry_staples.iterrows():
            col_idx = idx % num_cols
            with cols[col_idx]:
                col_item, col_del = st.columns([3, 1])
                with col_item:
                    st.write(f"• {staple['ingredient']}")
                with col_del:
                    if st.button("🗑️", key=f"del_pantry_{idx}"):
                        updated_pantry = pantry_staples.drop(idx)
                        save_pantry(updated_pantry)
                        st.rerun()
        
        # Quick suggestions based on common items
        st.divider()
        st.subheader("💡 Common Pantry Items")
        common_items = ["Salt", "Pepper", "Olive oil", "Garlic", "Onion", "Rice", "Pasta", "Flour", "Sugar", "Butter"]
        existing = pantry_staples['ingredient'].str.lower().tolist()
        suggestions = [item for item in common_items if item.lower() not in existing]
        
        if suggestions:
            cols = st.columns(5)
            for idx, item in enumerate(suggestions[:5]):
                with cols[idx]:
                    if st.button(f"➕ {item}", key=f"add_common_{item}"):
                        new_df = pd.DataFrame({"ingredient": [item]})
                        updated_pantry = pd.concat([pantry_staples, new_df], ignore_index=True)
                        save_pantry(updated_pantry)
                        st.rerun()
    else:
        st.info("No pantry staples yet. Add ingredients you always have at home!")

# ============================================================
# ✏️ TAB 5: Add / Edit Recipes
# ============================================================
with tabs[5]:
    st.header("Add or Modify Recipes")

    with st.expander("➕ Add New Recipe"):
        new_recipe_name = st.text_input("Recipe name")
        col1, col2, col3 = st.columns(3)
        with col1:
            new_cook_time = st.text_input("Cook time (optional, e.g. '30 mins')")
            new_rating = st.selectbox("Rating (optional):", [""] + [str(i) for i in range(1, 6)])
        with col2:
            new_source = st.text_input("Source (optional, e.g. 'BBC Good Food')")
            new_source_url = st.text_input("Source URL (optional)")
        with col3:
            new_cost = st.number_input("Estimated cost (£, optional):", min_value=0.0, step=0.50, value=0.0)
            new_prep_friendly = st.checkbox("Meal prep friendly?")
        
        new_tags = st.text_input("Tags (comma-separated, optional)")
        new_ingredients = st.text_area("Ingredients (one per line, e.g. 'Chicken breast,300,g,Protein' or 'Chicken breast,300,g' if no category)")

        if st.button("Add Recipe"):
            if new_recipe_name and new_ingredients:
                new_rows = []
                recipe_id = str(uuid.uuid4())  # Generate ONE recipe_id for the entire recipe
                for line in new_ingredients.strip().split("\n"):
                    parts = [x.strip() for x in line.split(",")]
                    try:
                        if len(parts) == 4:
                            ing, qty, unit, cat = parts
                        elif len(parts) == 3:
                            ing, qty, unit = parts
                            cat = ""  # Category is optional
                        else:
                            st.error(f"Invalid line format: {line}. Expected 3 or 4 comma-separated values.")
                            continue
                        
                        new_rows.append({
                            "recipe_id": recipe_id,  # Same ID for all ingredients in this recipe
                            "recipe_name": new_recipe_name,
                            "ingredient": ing,
                            "quantity": float(qty),
                            "unit": unit,
                            "category": cat,
                            "tags": new_tags,
                            "cook_time": new_cook_time,
                            "rating": new_rating if new_rating else '',
                            "source": new_source,
                            "source_url": new_source_url,
                            "servings": 2,  # Default servings
                            "notes": "",
                            "estimated_cost": new_cost,
                            "prep_friendly": new_prep_friendly
                        })
                    except ValueError as e:
                        st.error(f"Error parsing line '{line}': {e}")
                        
                if new_rows:
                    new_df = pd.DataFrame(new_rows)
                    updated = pd.concat([recipes, new_df], ignore_index=True)
                    save_data(updated)
                    st.rerun()
            else:
                st.warning("Please fill in the recipe name and ingredients.")
    
    # Recipe-level editor for metadata
    st.subheader("✏️ Edit Recipe Metadata")
    recipe_to_edit = st.selectbox("Select a recipe to edit:", [""] + sorted(recipes["recipe_name"].unique()))
    
    if recipe_to_edit:
        recipe_data = recipes[recipes["recipe_name"] == recipe_to_edit].iloc[0]
        
        with st.form(f"edit_recipe_{recipe_to_edit}"):
            st.write(f"**Editing: {recipe_to_edit}**")
            
            new_name = st.text_input("Recipe Name:", value=recipe_to_edit)
            
            col1, col2, col3 = st.columns(3)
            with col1:
                new_cook = st.text_input("Cook Time:", value=recipe_data.get('cook_time', ''))
                new_servings = st.number_input("Servings:", min_value=1, max_value=20, value=int(recipe_data.get('servings', 2)))
            with col2:
                # Fix rating index calculation
                rating_val = recipe_data.get('rating', '')
                if pd.isna(rating_val) or rating_val == '' or str(rating_val).strip() == '':
                    rating_idx = 0
                else:
                    try:
                        rating_idx = int(float(rating_val))
                    except (ValueError, TypeError):
                        rating_idx = 0
                
                new_rating_edit = st.selectbox("Rating:", [""] + [str(i) for i in range(1, 6)], index=rating_idx)
                new_src = st.text_input("Source:", value=recipe_data.get('source', ''))
            with col3:
                new_tags_edit = st.text_input("Tags:", value=recipe_data.get('tags', ''))
                new_src_url = st.text_input("Source URL:", value=recipe_data.get('source_url', ''))
            
            new_notes = st.text_area("Notes:", value=recipe_data.get('notes', ''))
            
            col_submit, col_delete, col_duplicate = st.columns(3)
            
            with col_submit:
                if st.form_submit_button("💾 Save Changes", type="primary"):
                    # Update all rows for this recipe
                    recipes.loc[recipes["recipe_name"] == recipe_to_edit, "recipe_name"] = new_name
                    recipes.loc[recipes["recipe_name"] == new_name, "cook_time"] = new_cook
                    recipes.loc[recipes["recipe_name"] == new_name, "rating"] = new_rating_edit if new_rating_edit else ''
                    recipes.loc[recipes["recipe_name"] == new_name, "source"] = new_src
                    recipes.loc[recipes["recipe_name"] == new_name, "source_url"] = new_src_url
                    recipes.loc[recipes["recipe_name"] == new_name, "tags"] = new_tags_edit
                    recipes.loc[recipes["recipe_name"] == new_name, "servings"] = new_servings
                    recipes.loc[recipes["recipe_name"] == new_name, "notes"] = new_notes
                    save_data(recipes)
                    st.rerun()
            
            with col_delete:
                if st.form_submit_button("🗑️ Delete Recipe", type="secondary"):
                    updated = recipes[recipes["recipe_name"] != recipe_to_edit]
                    save_data(updated)
                    st.rerun()
            
            with col_duplicate:
                if st.form_submit_button("📋 Duplicate Recipe"):
                    recipe_rows = recipes[recipes["recipe_name"] == recipe_to_edit].copy()
                    new_recipe_id = str(uuid.uuid4())
                    recipe_rows["recipe_id"] = new_recipe_id
                    recipe_rows["recipe_name"] = f"{recipe_to_edit} (Copy)"
                    updated = pd.concat([recipes, recipe_rows], ignore_index=True)
                    save_data(updated)
                    st.rerun()

    st.subheader("🧩 Edit Individual Ingredients")
    st.write("Use the editor below to modify individual ingredient quantities, units, and categories:")
    editable = st.data_editor(recipes, num_rows="dynamic", use_container_width=True)
    if st.button("💾 Save Ingredient Changes"):
        save_data(editable)
        st.rerun()

# ============================================================
# 📚 TAB 6: Meal History
# ============================================================
with tabs[6]:
    st.header("📚 Meal History")
    
    if not meal_history.empty:
        # Search/filter
        search_history = st.text_input("🔍 Search history (recipe name or date):")
        
        st.subheader("Past Meals")
        
        # Group by week
        history_display = meal_history.copy()
        history_display['week_start'] = pd.to_datetime(history_display['week_start'])
        history_display = history_display.sort_values('week_start', ascending=False)
        
        # Apply search filter
        if search_history:
            history_display = history_display[
                history_display['recipe_name'].str.contains(search_history, case=False, na=False) |
                history_display['week_start'].astype(str).str.contains(search_history, case=False, na=False)
            ]
        
        if history_display.empty:
            st.info("No matching history found.")
        else:
            # Display by week
            for week_start in history_display['week_start'].unique():
                week_recipes = history_display[history_display['week_start'] == week_start]
                week_str = pd.to_datetime(week_start).strftime('%B %d, %Y')
                
                with st.expander(f"📅 Week of {week_str} ({len(week_recipes)} recipes)"):
                    for idx, row in week_recipes.iterrows():
                        col1, col2 = st.columns([4, 1])
                        with col1:
                            st.write(f"• {row['recipe_name']}")
                        with col2:
                            if st.button("🗑️", key=f"delete_history_{idx}"):
                                updated_history = meal_history.drop(idx)
                                save_history(updated_history)
                                st.rerun()
        
        # Statistics
        st.subheader("📊 Statistics")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Weeks Tracked", history_display['week_start'].nunique())
        with col2:
            st.metric("Total Meals Recorded", len(history_display))
        with col3:
            st.metric("Unique Recipes", history_display['recipe_name'].nunique())
        
        # Most cooked recipes
        if len(history_display) > 0:
            st.subheader("⭐ Most Cooked Recipes")
            top_recipes = history_display['recipe_name'].value_counts().head(5)
            for recipe, count in top_recipes.items():
                st.write(f"**{recipe}**: {count} times")
        
        # Export history
        st.subheader("Export History")
        history_csv = meal_history.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="💾 Download Full Meal History (CSV)",
            data=history_csv,
            file_name="meal_history.csv",
            mime="text/csv"
        )
        
        # Clear history
        if st.button("🗑️ Clear All History", type="secondary"):
            if st.button("⚠️ Confirm Clear History"):
                save_history(pd.DataFrame(columns=["week_start", "recipe_name"]))
                st.rerun()
    else:
        st.info("No meal history yet. Save your weekly meals from the Weekly Planner tab to start tracking!")
