import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from urllib.parse import quote
from datetime import time
import os
import requests

st.set_page_config(layout="wide")

# --- Load and prepare data ---
df = pd.read_csv("Amneties_Final.csv")
df.columns = df.columns.str.strip()
df["opening_hour_clean"] = df["opening_hour"]
df["closing_hour_clean"] = df["closing_hour"]
df["opening_time"] = pd.to_datetime(df["opening_hour"], format="%H:%M").dt.time
df["closing_time"] = pd.to_datetime(df["closing_hour"], format="%H:%M").dt.time

def is_open_at_interval(open_time, close_time, start_hour, end_hour):
    # Convert to comparable floats (hour + fraction)
    open_h = open_time.hour + open_time.minute / 60
    close_h = close_time.hour + close_time.minute / 60

    if start_hour < end_hour:
        # Interval doesn’t cross midnight
        return (open_h < end_hour) and (close_h > start_hour)
    else:
        # Interval crosses midnight (e.g. 21 to 5)
        return (open_h < end_hour) or (close_h > start_hour)

df['open_morning'] = df.apply(lambda r: is_open_at_interval(r['opening_time'], r['closing_time'], 5, 12), axis=1)
df['open_midday'] = df.apply(lambda r: is_open_at_interval(r['opening_time'], r['closing_time'], 12, 17), axis=1)
df['open_evening'] = df.apply(lambda r: is_open_at_interval(r['opening_time'], r['closing_time'], 17, 21), axis=1)
df['open_night'] = df.apply(lambda r: is_open_at_interval(r['opening_time'], r['closing_time'], 21, 5), axis=1)

# --- Sidebar filters ---
st.sidebar.title("Filter Options")
amenity_options = ["All"] + sorted(df['amenity'].unique())
selected_amenity = st.sidebar.selectbox("Amenity Type", amenity_options)
show_night = st.sidebar.checkbox("Only show places open at night", value=False)
selected_hour = st.sidebar.slider("Select Hour (24h)", 0, 23, 12)
selected_time = time(selected_hour, 0)

def is_open_at(hour, open_time, close_time):
    if open_time < close_time:
        return open_time <= hour < close_time
    else:
        return hour >= open_time or hour < close_time

# Initial filtering
if selected_amenity == "All":
    filtered = df.copy()
else:
    filtered = df[df["amenity"] == selected_amenity]

if show_night:
    filtered = filtered[filtered["open_night"] == 1]

filtered = filtered[
    filtered.apply(lambda row: is_open_at(selected_time, row["opening_time"], row["closing_time"]), axis=1)
]

# --- Mapbox styles ---
MAPBOX_TOKEN = "pk.eyJ1IjoiYWxleGF2YWwiLCJhIjoiY21ib3VqeW9jMDF3bTJqc2FsYXg3eXZtdyJ9.-SREo-5j4jMGJ8e8Bhbmzw"
MAPBOX_STYLES = {
    "dawn": f"https://api.mapbox.com/styles/v1/alexaval/cmbrv82lu00z101qwbhjn0k8a/tiles/{{z}}/{{x}}/{{y}}?access_token={MAPBOX_TOKEN}",
    "day": f"https://api.mapbox.com/styles/v1/alexaval/cmbrvisot00uk01qx04914c3i/tiles/{{z}}/{{x}}/{{y}}?access_token={MAPBOX_TOKEN}",
    "dusk": f"https://api.mapbox.com/styles/v1/alexaval/cmbrut16a010u01sc784d2857/tiles/{{z}}/{{x}}/{{y}}?access_token={MAPBOX_TOKEN}",
    "night": f"https://api.mapbox.com/styles/v1/alexaval/cmbru8b5v00yu01r030sw4ack/tiles/{{z}}/{{x}}/{{y}}?access_token={MAPBOX_TOKEN}"
}

if 5 <= selected_hour < 12:
    time_period = "dawn"
elif 12 <= selected_hour < 17:
    time_period = "day"
elif 17 <= selected_hour < 21:
    time_period = "dusk"
else:
    time_period = "night"

# --- Session state initialization ---
if "map_center" not in st.session_state:
    default_center = [filtered['lat'].mean(), filtered['lon'].mean()] if not filtered.empty else [44.43, 26.10]
    st.session_state["map_center"] = default_center
if "map_zoom" not in st.session_state:
    st.session_state["map_zoom"] = 13

if "search_updated" not in st.session_state:
    st.session_state["search_updated"] = False

# Main page title and info
st.title("📍 Bucharest Amenities Dashboard")


# --- Search input ---
search_query = st.text_input("🔍 Search location (e.g. Lipscani, Aviatorilor)", value="")

if st.button("Search") or (search_query and not st.session_state.get("last_search") == search_query):
    # Only trigger on explicit search button or new input change
    try:
        url = f"https://nominatim.openstreetmap.org/search"
        params = {"q": search_query, "format": "json", "limit": 1}
        response = requests.get(url, params=params, headers={"User-Agent": "Streamlit-App"})
        data = response.json()
        if data:
            lat = float(data[0]["lat"])
            lon = float(data[0]["lon"])
            st.session_state["map_center"] = [lat, lon]
            st.session_state["map_zoom"] = 16
            st.session_state["search_updated"] = True
            if "map_bounds" in st.session_state:
                del st.session_state["map_bounds"]
            st.session_state["last_search"] = search_query
            st.success(f"Found: {data[0]['display_name']}")
        else:
            st.warning("No results found.")
    except Exception as e:
        st.error(f"Geocoding error: {e}")

# --- Filtering by bounds only if not recently searched ---
if "map_bounds" in st.session_state and not st.session_state.get("search_updated", False):
    bounds = st.session_state["map_bounds"]
    lat_min = bounds["_southWest"]["lat"]
    lat_max = bounds["_northEast"]["lat"]
    lon_min = bounds["_southWest"]["lng"]
    lon_max = bounds["_northEast"]["lng"]

    filtered = filtered[
        (filtered["lat"] >= lat_min) & (filtered["lat"] <= lat_max) &
        (filtered["lon"] >= lon_min) & (filtered["lon"] <= lon_max)
    ].head(300)
else:
    filtered = filtered.head(300)

# --- Amenity colors ---
amenity_colors = {
    "cafe": "#6f4e37",
    "restaurant": "#d35400",
    "pub": "#2980b9",
    "park": "#27ae60",
}

# --- Create map ---
m = folium.Map(
    location=st.session_state["map_center"],
    zoom_start=st.session_state["map_zoom"],
    tiles=None
)

m.options['preferCanvas'] = True

folium.TileLayer(
    tiles=MAPBOX_STYLES[time_period],
    attr="Mapbox",
    name=f"Mapbox {time_period}",
    max_zoom=18,
    detect_retina=False,
).add_to(m)

# --- Add markers ---
for _, row in filtered.iterrows():
    color = amenity_colors.get(row['amenity'].lower(), "#555555")

    popup_html = f"""
    <div style="
        font-family: Arial, sans-serif; 
        font-size: 14px; 
        border-radius: 6px; 
        overflow: hidden;
        box-shadow: 0 2px 6px rgba(0,0,0,0.3);
        width: 220px;
    ">
      <div style="
          background-color: {color};
          color: white;
          padding: 8px 12px;
          font-weight: bold;
          font-size: 16px;
          text-align: center;
      ">
        {row['name']}
      </div>
      <div style="padding: 8px 12px; color: #333;">
        <div>Open: {row['opening_hour_clean']} → {row['closing_hour_clean']}</div>
        <div style="margin-top: 6px;">
          <a href="{quote(str(row['website']), safe=':/?=&')}" target="_blank" style="color:#1E90FF; text-decoration:none;">Website</a>
        </div>
      </div>
    </div>
    """

    icon_file = f"ICONS/{row['amenity'].lower()}.png"
    icon_path = os.path.join(os.getcwd(), icon_file)
    if os.path.exists(icon_path):
        icon = folium.CustomIcon(icon_image=icon_path, icon_size=(30, 30))
    else:
        icon = folium.Icon(color="blue", icon="info-sign")

    folium.Marker(
        location=[row["lat"], row["lon"]],
        popup=folium.Popup(popup_html, max_width=250),
        icon=icon
    ).add_to(m)

# --- Render map ---
map_data = st_folium(m, use_container_width=True, height=700)

st.markdown("""
<style>
iframe.stCustomComponentV1 {
    border-radius: 15px;
    height: 700px !important;
    min-height: 700px !important;
    max-height: 700px !important;
    overflow: hidden !important;
    margin-bottom: -50px;  /* pulls the next section up */
}
</style>
""", unsafe_allow_html=True)

# --- Update session state ---
if map_data:
    if "center" in map_data and "zoom" in map_data:
        st.session_state["map_center"] = [map_data["center"]["lat"], map_data["center"]["lng"]]
        st.session_state["map_zoom"] = map_data["zoom"]
    if "bounds" in map_data:
        st.session_state["map_bounds"] = map_data["bounds"]
    # Reset search_updated after map interaction so next bounds filtering works
    st.session_state["search_updated"] = False

import plotly.express as px

time_rename = {
    'open_dawn': 'Morning',
    'open_day': 'Midday',
    'open_dusk': 'Evening',
    'open_night': 'Night'
}

# Count by amenity bar chart
amenity_counts = df['amenity'].value_counts().reset_index()
amenity_counts.columns = ['amenity', 'count']

fig1 = px.bar(
    amenity_counts,
    x='amenity',
    y='count',
    title="Count of Amenities by Type",
    labels={'count': 'Number of Places', 'amenity': 'Amenity Type'},
    color='amenity',
    color_discrete_sequence=px.colors.qualitative.Safe
)
st.plotly_chart(fig1, use_container_width=True)

# Overall amenities open by time of day (with renamed times)
time_period_cols = list(time_rename.keys())
time_period_counts = df[time_period_cols].sum().reset_index()
time_period_counts.columns = ['time_period', 'count']
time_period_counts['time_period'] = time_period_counts['time_period'].map(time_rename)

fig2 = px.bar(
    time_period_counts,
    x='time_period',
    y='count',
    title="Amenities Open by Time of Day",
    labels={'count': 'Number Open', 'time_period': 'Time Period'},
    color='time_period',
    color_discrete_sequence=px.colors.qualitative.Safe
)
st.plotly_chart(fig2, use_container_width=True)

# Four pie charts with nice titles
col1, col2, col3, col4 = st.columns(4)

time_map = {
    'open_dawn': col1,
    'open_day': col2,
    'open_dusk': col3,
    'open_night': col4
}

for time_col, col in time_map.items():
    subset = df[df[time_col] == 1]
    counts = subset['amenity'].value_counts().reset_index()
    counts.columns = ['amenity', 'count']
    fig = px.pie(
        counts,
        names='amenity',
        values='count',
        title=time_rename[time_col],  # Use renamed titles here
        color_discrete_sequence=px.colors.qualitative.Safe
    )
    col.plotly_chart(fig, use_container_width=True)

# Show custom curated sample database
st.markdown("### 📄 Sample of the Curated Database (Two of Each Type)")

sample_df = pd.read_csv("Amneties_Final_sample.csv")
st.dataframe(sample_df)

# --- Project Summary & Reflection ---
st.markdown("## 🧭 Project Reflection & Background")

st.markdown("""
Hello! I am Alex and this is my first serious analyst project in my portfolio. I have chosen a subject which I was more familiar with, so I can follow the data and more accurately check for information. Also this had a larger data pool I could access with online sources, giving me enough material for a large project. 
The tools I have used are:
-Geodata/Overpass Turbo
-Google Sheets/Excel
-MySql
-Tableau Viz
-Streamlit
-Photoshop and Illustrator (for icons)
-Mapbox (for the custom maps)

The idea was simple: have an interactive map of Bucharest’s best locations to visit for a day (or night) out. Places that are accessible, unique in entertainment or theme and whom’s got a good price range to go out. The map also had all the locations filtered and themed so you can check if you are at a certain time in a place and need to see what’s around you. Useful as a tourist or if you simply have a spontaneous night out and want to discover what’s new next to you. 

First step was to gather the raw data to work with. I’ve used overpass-turbo for this. I’ve used a filter by amenity ( bar, pub, nightclub, restaurant, café, cinema, theatre) within the Bucharest area. The related code for getting the data was:
""")
st.code("""
[out:json][timeout:25];
(
  node["amenity"~"bar|pub|cafe|nightclub|restaurant|theatre|cinema"](around:15000,44.4268,26.1025);
);
out body;
>;
out skel qt;
""", language="text")
st.markdown("""
The database itself is quite large, with over 2500 rows of locations that include the coordinates, website, type and opening hours. 

Now the real work began. Although huge, Overpass gave me a lot of duplicates, places that closed down, had missing info like websites and amenity type and the worst were the hours. Was either mismatching with current data, or the hours were split by day, such making the data clustered.
""")
st.image("Screenshots/1.jpg", use_container_width=True)
st.markdown("""
Time for clean up. Had to organize a pipeline and check everything. I’ve started from the simplest tasks and moved up such as:

1. Remove duplicates. Easy peasy.
2. Clean the split schedule into one cell, with a general window of opening hours that would apply. This way it would be much easier for other data programs to read and add a filter.
3. Filter by missing websites. Here I had to actually check every entry manually and add the relevant website, from different sources such as Google Maps, Facebook, Instagram or personal domain. It took a long time.
4. Check the location validity. As mentioned previously, the dataset was huge but I noticed a lot of places that I was aware didn’t exist anymore. This is when I took every entry manually, again, and this time checked on google maps if it still exists. Many were gone and others changed their name. 
5. Check the location’s quality. During step 4, I’ve also checked places that were themed, nice looking and not in dangerous neighbors.
A lengthy and grinding process of cleaning but was worth as from 2500 entries I trimmed it down to 1200 with full and current data.
6. Final step to remove categories and cells not needed, rename the columns properly and check the rows are all consistent. 


Now that the base was ready and clean, it was time to format it for SQL and Tableau. 
1. Checking the coordinates to have the same length and format. 
2. Have the hours in the 24h format. Here was more work as the cells had multiple types, many am-pm, others were 24h and some had the hours written with letters -_-
""")
st.image("Screenshots/2.jpg", use_container_width=True)
st.markdown("""
Here is where the Excel formulas were used intensively.  After changing all the hours into numerical format, I’ve then removed extra characters not needed such as seconds, changed the separators in proper type (many had *_* or *,* instead of *:* ) and then approximated and rounded the hours that had half hours(like 16:45 or 13:30). This step was important for the filter on Tableau to work.
Then filtered by time format and switched the cells in 12h format into 24h.Formula used is 

=TEXT(TIMEVALUE(G5),"HH:mm") 

as the original data was a text string.

Then lastly I had to separate the opening and closing hours into different columns, important for Tableau functions to work. I got lazy here and simply used LEFT(G5,5) and RIGHT(G5,5) and I simply split the opening and closing hours (5 as the complete hour has 5 characters like 13:00). In the end I also had to check for the places opened after midnight as Tableau had an issue of continuity, where 00:00-00:00 read as opened for a second. For this reason instead of 00:00 I’ve changed to 23:59 so it can read the location as being open for 24 hours.

Final dataset was optimized and looked like this: """)

st.image("Screenshots/3.jpg", use_container_width=True)
st.markdown("""
Everything was ready for Tableau. Imported, visualized, celebrated. I had a few hiccups now with the data. For example Tableau couldn’t read the hours as Sheets sneakily had a different format for the hours making them AM-PM even with the 24 hour format because of the formulas. I had to copy the values, paste into a new cell and assign the type manually (don’t forget to paste special: column values only otherwise the data will break because of the formulas). Then my coordinates were strings and couldn’t read as decimals for mapping. Why? After some detective work I discovered it was from the system itself. I had to navigate in Windows settings and change the decimal separator from comma to dot so Tableau could read it properly.

PROGRESS.

Now the data in, map format ready and all data is working.

I’ve created a set of custom icons to use as legend for the map in Photoshop and Illustrator. """)

st.image("Screenshots/6.jpg", use_container_width=True)
st.image("Screenshots/7.jpg", use_container_width=True)
st.markdown("""
For the custom maps there isn’t much to say. I’ve used mapbox and customized a map. I changed the colors and created 4 versions for each time of day(morning, afternoon, evening, night) and created a simple CRT texture and a watercolour texture that I applied in layers so I can give it a more handcrafted look.


For Tableau the process felt like a drawing board of figuring out ideas and implementing them. Here I will keep short as even though initially I created most of the visuals in it, Tableau decided to do an update and corrupted and deleted most of my work….

But the process here was helpful and helped me figure out the practicality and UX needs. The challenges I faced were:
-	I created 4 customs maps for each time of day but Tableau didn’t support dynamic maps. I went back and forth and the final solution was overlaying dashboards changing the maps by the time filter.

-	Made a time filter where the locations spots based by the hour. It was simple and the previous and painful process of cleaning all those hours helped here. A simple parameter did the trick""")

st.image("Screenshots/4.jpg", use_container_width=True)

st.markdown("""
For this filter to work I took my database in MySQL and created a Boolean assigning the four times of day on each location. This filter calculated the overall hour windows and if it’s opened during that time.

The formula went like this: """)

st.code("""SELECT * FROM bucharest_amneties.locations;
SET SQL_SAFE_UPDATES = 0;
UPDATE locations
SET open_dawn = NULL,
    open_day = NULL,
    open_dusk = NULL,
    open_night = NULL;


UPDATE locations
SET open_day = TRUE
WHERE
 (
    -- Normal hours (same day)
    opening_hour < closing_hour AND
    opening_hour <= '17:00:00' AND closing_hour >= '12:00:00'
  )
  OR
  (
    -- Overnight hours
    opening_hour > closing_hour AND
    (
      '12:00:00' >= opening_hour OR '17:00:00' <= closing_hour
    )
  )""", language="text")

st.markdown("""And then I repeated this query for each time of the day for their appropriate time windows. """)

st.image("Screenshots/5.jpg", use_container_width=True)
st.markdown("""
These Booleans helped a lot as now the program will know immediately when is opened without having to use complicated formulas within it. It avoids a lot of cluster and troubleshooting. 

And the process went on. I’ve had calculated fields as filters for locations to appear depending on amenity and hour, then I created a way to visualize each location’s details when clicking on it. I had made custom banners and formatted a tool tip so I can get the closest result to a pop up. Unfortunately this data was lost in that update.

At this moment when I lost the project, I was in a predicament. I had to either take it from the beginning and spend even more time just recreating the steps and calculated fields, or switch to Streamlit, who can do all the UX tasks I wanted and was much faster.

Tableau helped me figure out and brainstorm the whole look and utility of this project, let me actually visualize the result and the technical challenges allowed me to choose the best way to create it and what filters I wanted. 

So with an overall “sketch” and blueprint of the project I moved onto Streamlit. The process was much faster and Streamlit provided all the functions I wanted: dynamic map changes, filters, data and charts on one page etc.

Only issue was that it was a pure Python program, relying on code. Here I have asked the help of my “assistant”, ChatGPT and compiled the base code I needed to move faster and edit where I needed. It was an emergency choice as my project was nuked by Tableau and I didn’t want be on hold for long. 

And here we are. The final project, with interesting ideas and challenges that helped me develop a pipeline, data safeguards and formulas to speed up the process!



""")

