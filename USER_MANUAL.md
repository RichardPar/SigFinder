# SigFinder User Manual

## Table of Contents
- [Overview](#overview)
- [Main Window](#main-window)
- [Menu Options](#menu-options)
  - [File Menu](#file-menu)
  - [View Menu](#view-menu)
  - [Settings Menu](#settings-menu)
  - [Analyse Menu](#analyse-menu)
  - [Help Menu](#help-menu)
- [Signal Analysis Window](#signal-analysis-window)
- [Workflow Guide](#workflow-guide)

## Overview

SigFinder is a GPS-based signal strength mapping tool that combines SDR (Software Defined Radio) hardware with GPS data to visualise and analyse radio frequency signals. The application provides real-time mapping, CSV logging, and advanced signal analysis features.

## Main Window

The main window displays an interactive map with your current GPS position and signal strength information. The map updates in real-time as you move and detect signals.

### Map Features
- **Current Position Marker**: Shows your live GPS location
- **Triggered Markers**: Red circle markers placed automatically when RSSI exceeds the configured trigger threshold (minimum 50m spacing)
- **GPS Overlay**: Displays time, position, fix quality, satellites, and RSSI information
- **RSSI Graph**: Optional real-time graph showing signal strength over time

## Menu Options

### File Menu

#### New Session... (Ctrl+N)
Starts a new logging session and prompts you to choose a CSV file location.

**What it does:**
- Creates a new CSV file with headers for timestamp, GPS coordinates, signal data
- Enables logging of all RSSI measurements with GPS position
- File format: `Timestamp, Latitude, Longitude, Fix Quality, Num Satellites, RMC Status, RSSI (dBm)`

**When to use:**
- At the start of a signal hunting session
- When beginning a new area survey
- To separate different tracking sessions

#### Stop Session (Ctrl+S)
Stops the current logging session and closes the CSV file.

**What it does:**
- Safely closes the current CSV log file
- Disables further logging
- Resets the window title

**When to use:**
- When you've finished collecting data
- Before starting a new session in a different area
- To safely preserve your data

#### Session Pause (Ctrl+P) ☑️
Temporarily pauses CSV logging without closing the file.

**What it does:**
- Stops writing data to the CSV file while keeping the session active
- Checkbox shows current state (checked = paused, unchecked = active)
- Default state: OFF (not paused)

**When to use:**
- During transport between survey locations
- When taking a break but want to keep the same session
- To exclude unwanted data without starting a new file

#### Exit (Ctrl+Q)
Closes the application.

**What it does:**
- Safely closes any open CSV files
- Shuts down all SDR connections
- Exits the program

---

### View Menu

#### Centre on GPS (Ctrl+L)
Centres the map view on your current GPS position.

**What it does:**
- Moves the map to show your current location in the centre
- Zooms to an appropriate level (zoom level 14)

**When to use:**
- If you've panned/zoomed the map and lost track of your position
- After a long period of movement
- When starting a new search area

#### Show RSSI Graph (Ctrl+R) ☑️
Toggles the RSSI graph window visibility.

**What it does:**
- Opens/closes a separate window showing real-time RSSI measurements
- Graph updates continuously (5 times per second)
- Shows signal strength trends over time

**When to use:**
- To monitor signal strength changes in detail
- To identify signal patterns or oscillations
- During stationary measurements

---

### Settings Menu

#### Range Trigger...
Configures the RSSI threshold for automatic marker placement.

**What it does:**
- Opens a dialog to set the trigger level in dBm (e.g., -110 dBm)
- Range: -200.0 to 0.0 dBm
- When RSSI exceeds this value, a marker is automatically placed on the map

**How it works:**
- Markers are only added when RSSI *rises above* the threshold (rising edge detection)
- New markers must be at least 50 meters away from existing markers
- Each marker shows the RSSI value and GPS coordinates in a popup

**Typical values:**
- `-110 dBm`: Weak signal detection (long range)
- `-90 dBm`: Moderate signal detection
- `-70 dBm`: Strong signal detection (close range)

**When to adjust:**
- Set lower (more negative) for detecting distant/weak signals
- Set higher (less negative) for only marking strong/nearby signals
- Adjust based on your specific transmitter power and environment

#### Clear All Markers
Removes all triggered markers from the map.

**What it does:**
- Shows confirmation dialog with marker count
- Clears all red circle markers from the map
- Resets the internal marker tracking list

**When to use:**
- Starting a search in a new area
- After accidentally marking noise/interference
- To declutter the map view
- Before beginning a new tracking session

---

### Analyse Menu

#### Signal Analysis... (Ctrl+A)
Opens the Signal Analysis window for advanced data visualisation and origin estimation.

**What it does:**
- Opens a new window with a Leaflet map
- Can load one or multiple CSV files for analysis
- Performs advanced signal processing and origin prediction

**When to use:**
- After completing a survey session
- To analyse historical data
- To compare multiple tracking sessions
- To estimate transmitter location

See [Signal Analysis Window](#signal-analysis-window) for detailed features.

---

### Help Menu

#### About
Displays application information.

**What it shows:**
- Application name and version
- Brief description
- SDR hardware information

---

## Signal Analysis Window

The Signal Analysis window provides advanced tools for analysing logged signal data and estimating transmitter locations.

### File Menu (Analysis Window)

#### Open File(s)... (Ctrl+O)
Loads one or multiple CSV log files for analysis.

**Features:**
- Multi-file selection supported (Ctrl+Click or Shift+Click)
- Each file is analyzed separately with its own color
- Files are displayed as colored breadcrumbs on the map

#### Close (Ctrl+W)
Closes the Analysis window.

### Settings Menu (Analysis Window)

#### Minimum RSSI...
Sets the minimum signal strength threshold for analysis.

**What it does:**
- Filters out data points below this RSSI value
- Focuses analysis on significant detections
- Default: -100 dBm
- Re-runs analysis automatically after changing

**When to adjust:**
- Increase to remove noise floor data
- Decrease to include weaker signal detections

### Analysis Menu (Analysis Window)

#### Run Analysis (Ctrl+R)
Processes loaded data and updates the map visualisation.

**What it does:**
1. **Filters data** using minimum RSSI threshold
2. **Removes outliers** using IQR (Interquartile Range) method
3. **Detects oscillations** and removes noisy segments (>5 oscillations per 2 seconds)
4. **Estimates signal origin** for each dataset using:
   - Top 60% strongest signals
   - RSSI-weighted geometric centre
   - Widest NSEW (North-South-East-West) dimension
5. **Calculates combined origin** from all visible datasets
6. **Displays on map:**
   - Signal points as colored circles (green→yellow→orange→red by strength)
   - Individual file origin markers (dataset colors)
   - Combined origin marker (dark red bullseye)
   - 2-mile confidence radius circle (search area indicator)

### Map Features (Analysis Window)

**Signal Breadcrumbs:**
- Color-coded by signal strength (RSSI)
- Click for details: RSSI, GPS coordinates, duration
- Each file has a unique color

**Origin Markers:**
- Individual file origins: colored markers matching dataset
- Combined origin: dark red bullseye marker
- 2-mile confidence radius: dashed circle around combined origin

**Dataset Controls (Right Side Overlay):**
- Checkbox for each loaded file
- "Combined Origin" checkbox
- Toggle visibility of datasets
- Recalculates combined origin based on visible datasets only

### Advanced Features

**Outlier Detection:**
- Uses IQR method: Q1 - 1.5×IQR to Q3 + 1.5×IQR
- Removes statistical anomalies and spikes
- Improves origin accuracy

**Oscillation Filtering:**
- Detects rapid signal fluctuations (>2.5 per second)
- Removes unreliable/noisy segments
- Threshold: 5 oscillations per 2 seconds

**Origin Algorithm:**
- Prioritizes widest dimension (N-S or E-W) for better accuracy
- Weights by signal strength (stronger signals = more influence)
- Uses only top 60% of signals to reduce outlier impact
- Calculates confidence based on number of detection points

---

## Workflow Guide

### Basic Signal Hunting

1. **Start the application** and ensure GPS fix is acquired
2. **Set Range Trigger** (Settings → Range Trigger) to appropriate level (e.g., -110 dBm)
3. **Start New Session** (File → New Session) and choose a save location
4. Begin moving through your search area
5. **Triggered markers** automatically appear when signal exceeds threshold
6. **Centre on GPS** (View → Centre on GPS) if you lose track of position
7. **Stop Session** when complete to save data

### Advanced Analysis

1. Complete one or more signal hunting sessions
2. **Open Signal Analysis** (Analyse → Signal Analysis)
3. **Load CSV file(s)** (File → Open File(s))
4. Adjust **Minimum RSSI** threshold if needed
5. **Run Analysis** to see signal patterns and origin estimate
6. Toggle datasets on/off to compare different sessions
7. Use the **2-mile confidence radius** to focus your physical search

### Pausing Data Collection

1. While session is active, enable **Session Pause** (File → Session Pause)
2. GPS tracking continues but no data is written
3. Uncheck to resume logging
4. Useful for transit between locations or breaks

### Clearing Markers

1. Go to **Settings → Clear All Markers**
2. Confirm deletion
3. All triggered markers removed from map
4. Useful when starting a new area or after false triggers

---

## Tips and Best Practices

**For Best GPS Accuracy:**
- Wait for good GPS fix (3+ satellites) before starting
- Check GPS overlay shows green/valid position
- Avoid starting under heavy tree cover or buildings

**For Optimal Signal Detection:**
- Set Range Trigger based on expected signal strength
- Start conservative (lower/more negative) and adjust if too many false triggers
- Use Session Pause when not actively searching

**For Analysis:**
- Collect data from multiple angles/approaches for better origin estimate
- Use multiple sessions (different times/days) for comparison
- Check oscillation filtering removed noisy data
- 2-mile radius is a search area guide, not exact location

**Marker Management:**
- 50-meter minimum spacing prevents marker clutter
- Clear markers between different search areas
- Markers persist until manually cleared or session restart

---

## Troubleshooting

**No GPS fix:**
- Check GPS hardware connection
- Move to clear sky view
- Wait for satellite acquisition (can take 30-60 seconds)

**No markers appearing:**
- Check Range Trigger setting (Settings → Range Trigger)
- Verify signal is actually exceeding threshold (check RSSI Graph)
- Ensure you're 50+ meters from existing markers

**CSV file won't open for analysis:**
- Verify file has correct headers
- Check file isn't open in another program
- Ensure file contains data (not just headers)

**Analysis shows no origin:**
- Lower the Minimum RSSI threshold
- Verify CSV contains valid GPS coordinates
- Check that data points passed filtering (outliers/oscillations)

---

## Keyboard Shortcuts Reference

| Shortcut | Action |
|----------|--------|
| Ctrl+N | New Session |
| Ctrl+S | Stop Session |
| Ctrl+P | Session Pause (toggle) |
| Ctrl+Q | Exit |
| Ctrl+L | Centre on GPS |
| Ctrl+R | Show RSSI Graph (toggle) |
| Ctrl+A | Signal Analysis |

### Analysis Window Shortcuts

| Shortcut | Action |
|----------|--------|
| Ctrl+O | Open File(s) |
| Ctrl+W | Close Window |
| Ctrl+R | Run Analysis |

---

*For technical support or bug reports, please refer to the project repository.*
