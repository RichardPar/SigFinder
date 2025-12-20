"""
Analysis Window - Visualize signal data from CSV logs
"""
import csv
import os
from datetime import datetime
import math
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QLabel, QLineEdit, QFileDialog, QMessageBox, QInputDialog,
    QSlider, QComboBox
)
from PyQt6.QtGui import QAction
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtCore import QUrl, Qt


class AnalysisWindow(QMainWindow):
    """Window for analysing CSV log data and visualising signal patterns"""
    
    def __init__(self, parent=None, current_csv_file=None):
        super().__init__(parent)
        self.current_csv_file = current_csv_file
        self.setWindowTitle("Signal Analysis")
        self.setGeometry(100, 100, 1000, 800)
        
        # Create menu bar
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu('&File')
        
        open_action = QAction('&Open File(s)...', self)
        open_action.setShortcut('Ctrl+O')
        open_action.setStatusTip('Open CSV log file(s) for analysis')
        open_action.triggered.connect(self.open_file)
        file_menu.addAction(open_action)
        
        file_menu.addSeparator()
        
        close_action = QAction('&Close', self)
        close_action.setShortcut('Ctrl+W')
        close_action.setStatusTip('Close analysis window')
        close_action.triggered.connect(self.close)
        file_menu.addAction(close_action)
        
        # Settings menu
        settings_menu = menubar.addMenu('&Settings')
        
        rssi_action = QAction('Minimum &RSSI...', self)
        rssi_action.setStatusTip('Set minimum RSSI threshold')
        rssi_action.triggered.connect(self.show_rssi_dialog)
        settings_menu.addAction(rssi_action)
        
        # Analysis menu
        analysis_menu = menubar.addMenu('&Analysis')
        
        analyse_action = QAction('&Run Analysis', self)
        analyse_action.setShortcut('Ctrl+R')
        analyse_action.setStatusTip('Analyse loaded data')
        analyse_action.triggered.connect(self.update_analysis)
        analysis_menu.addAction(analyse_action)
        
        # Create central widget and layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Hidden storage for RSSI value
        self.rssi_edit = QLineEdit()
        self.rssi_edit.setText("-100")
        self.rssi_edit.setVisible(False)
        
        # Hidden labels for internal tracking
        self.file_label = QLabel()
        self.file_label.setVisible(False)
        self.rssi_display = QLabel()
        self.rssi_display.setVisible(False)
        
        # Web view for map
        self.web_view = QWebEngineView()
        layout.addWidget(self.web_view)
        
        # Dataset checkboxes list (created dynamically)
        self.dataset_checkboxes = []
        self.dataset_checkbox_widgets = []  # Store the actual widget containers
        
        # Store current signal points and origin for updates
        self.current_signal_points = None
        self.current_origin = None
        # Heatmap state (safe canvas-based heat layer)
        self.show_heatmap = False
        self.heatmap_points = None
        # Heatmap UI defaults
        self.heatmap_radius = 25
        self.heatmap_opacity = 0.35
        self.heatmap_palette = 'Inferno'  # 'Inferno' | 'Viridis' | 'Yellow-Red'
        
        # Set initial file if provided
        if self.current_csv_file:
            self.file_label.setText(f"File: {os.path.basename(self.current_csv_file)}")
            self.update_analysis()
        else:
            self.show_empty_map()
    
    def show_rssi_dialog(self):
        """Show dialog to set minimum RSSI threshold"""
        current_value = float(self.rssi_edit.text())
        value, ok = QInputDialog.getDouble(
            self,
            'Minimum RSSI',
            'Set minimum RSSI threshold (dBm):',
            current_value,
            -200.0,
            0.0,
            1
        )
        if ok:
            self.rssi_edit.setText(str(value))
            self.rssi_display.setText(f"{value:.1f} dBm")
            # Auto-run analysis if data is loaded
            if self.current_csv_file:
                self.update_analysis()
    
    def open_file(self):
        """Open CSV file(s) for analysis"""
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Open CSV Log File(s)",
            "",
            "CSV Files (*.csv);;All Files (*)"
        )
        
        if file_paths:
            if len(file_paths) == 1:
                self.current_csv_file = file_paths[0]
                self.file_label.setText(f"File: {os.path.basename(file_paths[0])}")
            else:
                # Multiple files selected
                self.current_csv_file = file_paths  # Store list of files
                self.file_label.setText(f"Files: {len(file_paths)} selected")
            self.update_analysis()
    
    def update_analysis(self):
        """Analyse the current CSV file(s) and update the map"""
        if not self.current_csv_file:
            QMessageBox.warning(self, "No File", "Please select a CSV file to analyse.")
            return
        
        # Handle both single file and multiple files
        file_list = self.current_csv_file if isinstance(self.current_csv_file, list) else [self.current_csv_file]
        
        # Check if files exist
        for file_path in file_list:
            if not os.path.exists(file_path):
                QMessageBox.warning(self, "File Not Found", f"File not found: {file_path}")
                return
        
        try:
            min_rssi = float(self.rssi_edit.text())
        except ValueError:
            QMessageBox.warning(self, "Invalid Input", "Please enter a valid number for minimum RSSI.")
            return
        
        # Parse CSV and analyse signal data from each file separately
        file_datasets = []
        all_signal_points = []
        
        # Define colors for different files (cycling through if more files than colors)
        dataset_colors = ['#FF0000', '#00FF00', '#0000FF', '#FF00FF', '#FFFF00', '#00FFFF', '#FFA500', '#800080']
        
        for idx, file_path in enumerate(file_list):
            points = self.analyze_csv(file_path, min_rssi)
            if points:
                # Assign a color identifier to each point for this file
                dataset_color = dataset_colors[idx % len(dataset_colors)]
                for point in points:
                    point['dataset_id'] = idx
                    point['dataset_color'] = dataset_color
                    point['dataset_name'] = os.path.basename(file_path)
                
                # Calculate origin for this individual file
                file_origin = self.estimate_signal_origin(points)
                if file_origin:
                    file_origin['dataset_id'] = idx
                    file_origin['dataset_color'] = dataset_color
                    file_origin['dataset_name'] = os.path.basename(file_path)
                
                file_datasets.append({
                    'points': points,
                    'origin': file_origin,
                    'filename': os.path.basename(file_path),
                    'color': dataset_color
                })
                
                all_signal_points.extend(points)
        
        if not all_signal_points:
            QMessageBox.information(self, "No Data", "No signal points found above the minimum RSSI threshold.")
            self.show_empty_map()
            self.current_signal_points = None
            self.current_origin = None
            self.file_datasets = None
            return
        
        # Store signal points and datasets for re-estimation
        self.current_signal_points = all_signal_points
        self.file_datasets = file_datasets

        # Precompute simple heatmap points (aggregated) for fast rendering
        self.heatmap_points = self.compute_heatmap_points(all_signal_points)

        # Update dataset selection checkboxes
        self.update_dataset_checkboxes()
        
        # Calculate combined origin from all signal points
        combined_origin = self.estimate_signal_origin(all_signal_points)
        if combined_origin:
            combined_origin['dataset_id'] = -1  # Special ID for combined
            combined_origin['dataset_color'] = '#FF0000'  # Red for combined
            combined_origin['dataset_name'] = 'Combined'
        self.current_origin = combined_origin
        
        # Generate and display map with all datasets
        self.display_map_multi(file_datasets, combined_origin)
    
    def update_dataset_checkboxes(self):
        """Create or update checkboxes for dataset visibility control as overlay on map"""
        from PyQt6.QtWidgets import QCheckBox
        
        # Clear existing checkboxes
        for widget in self.dataset_checkbox_widgets:
            widget.deleteLater()
        self.dataset_checkbox_widgets.clear()
        self.dataset_checkboxes.clear()
        
        if not self.file_datasets:
            return
        
        y_position = 50
        
        # Add checkbox for each dataset
        for idx, dataset in enumerate(self.file_datasets):
            checkbox = QCheckBox(dataset['filename'], self.web_view)
            checkbox.setChecked(True)
            checkbox.setStyleSheet(f"""
                QCheckBox {{
                    background-color: rgba(255, 255, 255, 220);
                    color: {dataset['color']};
                    font-weight: bold;
                    padding: 8px 12px;
                    border-radius: 4px;
                    border: 2px solid {dataset['color']};
                }}
                QCheckBox::indicator {{
                    width: 18px;
                    height: 18px;
                }}
            """)
            checkbox.stateChanged.connect(lambda state, i=idx: self.on_dataset_toggle(i, state))
            checkbox.show()
            checkbox.raise_()
            self.dataset_checkbox_widgets.append(checkbox)
            self.dataset_checkboxes.append(checkbox)
            y_position += 40
        
        # Add combined checkbox
        combined_cb = QCheckBox("Combined Origin", self.web_view)
        combined_cb.setChecked(True)
        combined_cb.setStyleSheet("""
            QCheckBox {
                background-color: rgba(255, 255, 255, 220);
                color: #8B0000;
                font-weight: bold;
                padding: 8px 12px;
                border-radius: 4px;
                border: 2px solid #8B0000;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
            }
        """)
        combined_cb.stateChanged.connect(lambda state: self.on_dataset_toggle(-1, state))
        combined_cb.show()
        combined_cb.raise_()
        self.dataset_checkbox_widgets.append(combined_cb)
        self.dataset_checkboxes.append(combined_cb)
        
        # Add heatmap toggle (canvas-based heat layer)
        heatmap_cb = QCheckBox("Show Heatmap", self.web_view)
        heatmap_cb.setChecked(self.show_heatmap)
        heatmap_cb.setStyleSheet("""
            QCheckBox {
                background-color: rgba(255, 255, 255, 220);
                color: #333333;
                font-weight: bold;
                padding: 8px 12px;
                border-radius: 4px;
                border: 2px solid #444444;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
            }
        """)
        heatmap_cb.stateChanged.connect(lambda s: self.toggle_heatmap(2 if s else 0))
        heatmap_cb.show()
        heatmap_cb.raise_()
        self.dataset_checkbox_widgets.append(heatmap_cb)
        # Do not add to dataset_checkboxes (it's a control, not a dataset)
        
        # Radius slider
        radius_label = QLabel(f"Heat Radius: {self.heatmap_radius}px", self.web_view)
        radius_label.setStyleSheet("background: rgba(255,255,255,220); padding:4px; border-radius:4px; font-weight:bold;")
        radius_label.show(); radius_label.raise_()
        radius_slider = QSlider(Qt.Orientation.Horizontal, self.web_view)
        radius_slider.setMinimum(5)
        radius_slider.setMaximum(100)
        radius_slider.setValue(self.heatmap_radius)
        radius_slider.setFixedWidth(180)
        radius_slider.valueChanged.connect(lambda v: self.on_radius_changed(v, radius_label))
        radius_slider.show(); radius_slider.raise_()
        self.dataset_checkbox_widgets.append(radius_label)
        self.dataset_checkbox_widgets.append(radius_slider)

        # Opacity slider
        opacity_label = QLabel(f"Heat Opacity: {int(self.heatmap_opacity*100)}%", self.web_view)
        opacity_label.setStyleSheet("background: rgba(255,255,255,220); padding:4px; border-radius:4px; font-weight:bold;")
        opacity_label.show(); opacity_label.raise_()
        opacity_slider = QSlider(Qt.Orientation.Horizontal, self.web_view)
        opacity_slider.setMinimum(10)
        opacity_slider.setMaximum(100)
        opacity_slider.setValue(int(self.heatmap_opacity*100))
        opacity_slider.setFixedWidth(180)
        opacity_slider.valueChanged.connect(lambda v: self.on_opacity_changed(v, opacity_label))
        opacity_slider.show(); opacity_slider.raise_()
        self.dataset_checkbox_widgets.append(opacity_label)
        self.dataset_checkbox_widgets.append(opacity_slider)

        # Palette dropdown
        palette_combo = QComboBox(self.web_view)
        palette_combo.addItems(['Inferno', 'Viridis', 'Yellow-Red'])
        idx = {'Inferno':0,'Viridis':1,'Yellow-Red':2}.get(self.heatmap_palette, 0)
        palette_combo.setCurrentIndex(idx)
        palette_combo.setFixedWidth(160)
        palette_combo.currentTextChanged.connect(self.on_palette_changed)
        palette_combo.show(); palette_combo.raise_()
        self.dataset_checkbox_widgets.append(palette_combo)
        # Position all checkboxes
        self.position_checkboxes()
    
    def position_checkboxes(self):
        """Position checkboxes on the right side of the map"""
        web_width = self.web_view.width()
        if web_width == 0:
            web_width = 1000  # Default width
        
        y_position = 50
        for checkbox in self.dataset_checkbox_widgets:
            checkbox.adjustSize()
            x_position = web_width - checkbox.width() - 20
            checkbox.move(x_position, y_position)
            y_position += 45
    
    def on_dataset_toggle(self, dataset_id, state):
        """Handle dataset visibility toggle"""
        is_visible = (state == 2)  # Qt.CheckState.Checked = 2
        
        # Build list of visible datasets
        visible_datasets = []
        show_combined = True
        
        for idx, dataset in enumerate(self.file_datasets):
            if self.dataset_checkboxes[idx].isChecked():
                visible_datasets.append(dataset)
        
        # Check combined checkbox state
        if len(self.dataset_checkboxes) > len(self.file_datasets):
            show_combined = self.dataset_checkboxes[-1].isChecked()
        
        # Recalculate combined origin from visible datasets only
        if visible_datasets:
            all_visible_points = []
            for dataset in visible_datasets:
                all_visible_points.extend(dataset['points'])
            # Recompute heat points for the visible subset
            self.heatmap_points = self.compute_heatmap_points(all_visible_points)
            combined_origin = self.estimate_signal_origin(all_visible_points) if show_combined else None
            if combined_origin:
                combined_origin['dataset_id'] = -1
                combined_origin['dataset_color'] = '#FF0000'
                combined_origin['dataset_name'] = 'Combined'
            
            # Redraw map with only visible datasets
            self.display_map_multi(visible_datasets, combined_origin if show_combined else None)

    def on_radius_changed(self, value, label_widget):
        try:
            self.heatmap_radius = int(value)
            label_widget.setText(f"Heat Radius: {self.heatmap_radius}px")
            if self.show_heatmap:
                # Re-render map to apply new radius
                visible_datasets = []
                for idx, dataset in enumerate(self.file_datasets):
                    if self.dataset_checkboxes[idx].isChecked():
                        visible_datasets.append(dataset)
                show_combined = True
                if len(self.dataset_checkboxes) > len(self.file_datasets):
                    show_combined = self.dataset_checkboxes[-1].isChecked()
                combined_origin = None
                if visible_datasets and show_combined:
                    all_visible_points = []
                    for dataset in visible_datasets:
                        all_visible_points.extend(dataset['points'])
                    combined_origin = self.estimate_signal_origin(all_visible_points)
                self.display_map_multi(visible_datasets, combined_origin)
        except Exception:
            pass

    def on_opacity_changed(self, value, label_widget):
        try:
            self.heatmap_opacity = max(0.01, min(1.0, float(value) / 100.0))
            label_widget.setText(f"Heat Opacity: {int(self.heatmap_opacity*100)}%")
            if self.show_heatmap:
                # Re-render map to apply new opacity
                visible_datasets = []
                for idx, dataset in enumerate(self.file_datasets):
                    if self.dataset_checkboxes[idx].isChecked():
                        visible_datasets.append(dataset)
                show_combined = True
                if len(self.dataset_checkboxes) > len(self.file_datasets):
                    show_combined = self.dataset_checkboxes[-1].isChecked()
                combined_origin = None
                if visible_datasets and show_combined:
                    all_visible_points = []
                    for dataset in visible_datasets:
                        all_visible_points.extend(dataset['points'])
                    combined_origin = self.estimate_signal_origin(all_visible_points)
                self.display_map_multi(visible_datasets, combined_origin)
        except Exception:
            pass

    def on_palette_changed(self, text):
        try:
            self.heatmap_palette = text
            if self.show_heatmap:
                visible_datasets = []
                for idx, dataset in enumerate(self.file_datasets):
                    if self.dataset_checkboxes[idx].isChecked():
                        visible_datasets.append(dataset)
                show_combined = True
                if len(self.dataset_checkboxes) > len(self.file_datasets):
                    show_combined = self.dataset_checkboxes[-1].isChecked()
                combined_origin = None
                if visible_datasets and show_combined:
                    all_visible_points = []
                    for dataset in visible_datasets:
                        all_visible_points.extend(dataset['points'])
                    combined_origin = self.estimate_signal_origin(all_visible_points)
                self.display_map_multi(visible_datasets, combined_origin)
        except Exception:
            pass
        
    
    def analyze_csv(self, file_path, min_rssi):
        """
        Parse CSV file and extract signal points above threshold.
        Groups consecutive points to calculate signal duration.
        Filters out segments with excessive oscillation (>5 crossings per second).
        
        Returns list of dicts with: lat, lon, rssi, duration, color
        """
        signal_segments = []
        current_segment = None
        
        try:
            with open(file_path, 'r') as f:
                reader = csv.DictReader(f)
                
                for row in reader:
                    try:
                        # Handle both old and new CSV column formats
                        rssi = float(row.get('RSSI (dBm)', row.get('rssi_dbm', 0)))
                        lat = float(row.get('Latitude', row.get('latitude', 0)))
                        lon = float(row.get('Longitude', row.get('longitude', 0)))
                        timestamp_str = row.get('Timestamp', row.get('timestamp', ''))
                        
                        # Parse timestamp if available
                        timestamp = None
                        if timestamp_str:
                            try:
                                from datetime import datetime
                                timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                            except:
                                pass
                        
                        # Skip if below threshold or invalid GPS
                        if rssi < min_rssi or lat == 0.0 or lon == 0.0:
                            # End current segment if exists
                            if current_segment:
                                signal_segments.append(current_segment)
                                current_segment = None
                            continue
                        
                        # Start new segment or continue existing
                        if current_segment is None:
                            current_segment = {
                                'lat': lat,
                                'lon': lon,
                                'rssi_max': rssi,
                                'rssi_sum': rssi,
                                'rssi_values': [rssi],
                                'timestamps': [timestamp] if timestamp else [],
                                'count': 1,
                                'min_rssi_threshold': min_rssi
                            }
                        else:
                            # Check if close to previous point (within ~10 meters)
                            lat_diff = abs(lat - current_segment['lat'])
                            lon_diff = abs(lon - current_segment['lon'])
                            
                            if lat_diff < 0.0001 and lon_diff < 0.0001:
                                # Continue segment - update to latest position
                                current_segment['lat'] = lat
                                current_segment['lon'] = lon
                                current_segment['rssi_max'] = max(current_segment['rssi_max'], rssi)
                                current_segment['rssi_sum'] += rssi
                                current_segment['rssi_values'].append(rssi)
                                if timestamp:
                                    current_segment['timestamps'].append(timestamp)
                                current_segment['count'] += 1
                            else:
                                # Too far - end segment and start new one
                                signal_segments.append(current_segment)
                                current_segment = {
                                    'lat': lat,
                                    'lon': lon,
                                    'rssi_max': rssi,
                                    'rssi_sum': rssi,
                                    'rssi_values': [rssi],
                                    'timestamps': [timestamp] if timestamp else [],
                                    'count': 1,
                                    'min_rssi_threshold': min_rssi
                                }
                    
                    except (KeyError, ValueError) as e:
                        continue  # Skip malformed rows
                
                # Don't forget last segment
                if current_segment:
                    signal_segments.append(current_segment)
        
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Error reading file: {str(e)}")
            return []
        
        # Filter out segments with excessive oscillation and calculate final properties
        signal_points = []
        for segment in signal_segments:
            # Check for oscillation: count threshold crossings
            if len(segment['rssi_values']) > 1:
                oscillation_count = self.count_oscillations(segment['rssi_values'], segment['min_rssi_threshold'])
                
                # Calculate time span for rate calculation
                if len(segment['timestamps']) >= 2:
                    time_span = (segment['timestamps'][-1] - segment['timestamps'][0]).total_seconds()
                    if time_span > 0:
                        # Discard if more than 5 oscillations per 2 seconds (2.5 per second)
                        oscillation_rate = oscillation_count / time_span
                        if oscillation_rate > 2.5:
                            continue
                elif oscillation_count > 5:
                    # If no timestamps, assume ~20Hz sampling (RTL-SDR)
                    # For 2 seconds at 20Hz = 40 samples, so >5 oscillations in 40 samples is suspicious
                    estimated_time = len(segment['rssi_values']) / 20.0
                    if estimated_time > 0 and (oscillation_count / estimated_time) > 2.5:
                        continue
            
            # Remove outliers from RSSI values before calculating average
            cleaned_rssi_values = self.remove_outliers(segment['rssi_values'])
            
            if not cleaned_rssi_values:
                # All values were outliers, skip this segment
                continue
            
            rssi_avg = sum(cleaned_rssi_values) / len(cleaned_rssi_values)
            rssi_max = max(cleaned_rssi_values)
            rssi_above_threshold = rssi_max - segment['min_rssi_threshold']
            
            # Color based on signal strength above threshold
            # Green (best) -> Yellow -> Orange -> Red (threshold)
            color = self.calculate_color(rssi_above_threshold)
            
            # Size based on duration (sample count)
            # More samples = longer signal = larger circle
            radius = self.calculate_radius(len(cleaned_rssi_values))
            
            signal_points.append({
                'lat': segment['lat'],
                'lon': segment['lon'],
                'rssi_max': rssi_max,
                'rssi_avg': rssi_avg,
                'duration': len(cleaned_rssi_values),
                'color': color,
                'radius': radius
            })
        
        return signal_points

    def compute_heatmap_grid(self, points):
        # Deprecated placeholder kept for compatibility; new heatmap uses compute_heatmap_points
        return []

    def compute_heatmap_points(self, points):
        """Aggregate points into a list of [lat, lon, intensity] suitable for leaflet.heat.

        This uses a simple spatial binning (WebMercator 100m grid) and produces
        one sample point per cell with an intensity normalized by count and strength.
        """
        if not points:
            return []

        # Helpers to convert lon/lat to WebMercator meters and back
        def lonlat_to_meters(lon, lat):
            origin_shift = 2 * math.pi * 6378137 / 2.0
            mx = lon * origin_shift / 180.0
            my = math.log(math.tan((90 + lat) * math.pi / 360.0))
            my = my * origin_shift / math.pi
            return mx, my

        def meters_to_lonlat(mx, my):
            origin_shift = 2 * math.pi * 6378137 / 2.0
            lon = (mx / origin_shift) * 180.0
            lat = (my / origin_shift) * 180.0
            lat = 180 / math.pi * (2 * math.atan(math.exp(lat * math.pi / 180.0)) - math.pi / 2.0)
            return lon, lat

        cell_size_m = 100.0
        grid = {}
        for p in points:
            lat = p['lat']
            lon = p['lon']
            strength = float(p.get('rssi_avg', p.get('rssi_max', 0)))
            mx, my = lonlat_to_meters(lon, lat)
            gx = int(math.floor(mx / cell_size_m))
            gy = int(math.floor(my / cell_size_m))
            key = (gx, gy)
            if key not in grid:
                grid[key] = {'mx': mx, 'my': my, 'count': 1, 'strength_sum': strength}
            else:
                g = grid[key]
                g['mx'] += mx
                g['my'] += my
                g['count'] += 1
                g['strength_sum'] += strength

        # Build heat points (lat, lon, intensity)
        heat_points = []
        strengths = [g['strength_sum'] / g['count'] for g in grid.values()]
        min_s, max_s = (min(strengths), max(strengths)) if strengths else (0.0, 1.0)

        def norm(v, vmin, vmax):
            if vmax <= vmin:
                return 0.0
            return (v - vmin) / (vmax - vmin)

        for key, g in grid.items():
            avg_mx = g['mx'] / g['count']
            avg_my = g['my'] / g['count']
            lon_c, lat_c = meters_to_lonlat(avg_mx, avg_my)
            avg_strength = g['strength_sum'] / g['count']
            intensity = norm(avg_strength, min_s, max_s)
            # boost intensity slightly by count
            intensity = min(1.0, intensity * 0.7 + 0.3 * norm(g['count'], 1, max(g['count'], 1)))
            heat_points.append([lat_c, lon_c, intensity])

        return heat_points
    
    def remove_outliers(self, values):
        """
        Remove outliers using the Interquartile Range (IQR) method.
        Outliers are values that fall below Q1 - 1.5*IQR or above Q3 + 1.5*IQR.
        """
        if len(values) < 4:
            # Need at least 4 values for meaningful outlier detection
            return values
        
        # Sort values to calculate quartiles
        sorted_values = sorted(values)
        n = len(sorted_values)
        
        # Calculate Q1 (25th percentile) and Q3 (75th percentile)
        q1_idx = n // 4
        q3_idx = (3 * n) // 4
        q1 = sorted_values[q1_idx]
        q3 = sorted_values[q3_idx]
        
        # Calculate IQR
        iqr = q3 - q1
        
        # Calculate bounds
        lower_bound = q1 - 1.5 * iqr
        upper_bound = q3 + 1.5 * iqr
        
        # Filter out outliers
        cleaned = [v for v in values if lower_bound <= v <= upper_bound]
        
        return cleaned if cleaned else values  # Return original if all were outliers
    
    def count_oscillations(self, rssi_values, threshold):
        """
        Count the number of times the signal crosses the threshold.
        An oscillation is when the signal goes from above threshold to below or vice versa.
        """
        if len(rssi_values) < 2:
            return 0
        
        crossings = 0
        was_above = rssi_values[0] >= threshold
        
        for rssi in rssi_values[1:]:
            is_above = rssi >= threshold
            if is_above != was_above:
                crossings += 1
                was_above = is_above
        
        return crossings
    
    def estimate_signal_origin(self, signal_points):
        """
        Estimate the signal origin based on the widest area coverage and strongest signals.
        Finds the combination of points that creates the largest detection area with strong signals.
        """
        if not signal_points:
            return None
        
        if len(signal_points) == 1:
            return {
                'lat': signal_points[0]['lat'],
                'lon': signal_points[0]['lon'],
                'ns_span': 0,
                'ew_span': 0,
                'confidence': 1
            }
        
        # Strategy: Find the widest area using strong signals
        # Use only signals in the top 60% by strength
        sorted_by_strength = sorted(signal_points, key=lambda p: p['rssi_max'], reverse=True)
        strong_signals = sorted_by_strength[:max(2, int(len(sorted_by_strength) * 0.6))]
        
        # Find extreme points in each direction among strong signals
        northmost = max(strong_signals, key=lambda p: p['lat'])
        southmost = min(strong_signals, key=lambda p: p['lat'])
        eastmost = max(strong_signals, key=lambda p: p['lon'])
        westmost = min(strong_signals, key=lambda p: p['lon'])
        
        # Calculate spans
        ns_span = northmost['lat'] - southmost['lat']
        ew_span = eastmost['lon'] - westmost['lon']
        
        # Use the center of the widest dimension's extreme points
        # Weight the center calculation by signal strength
        if ns_span >= ew_span:
            # North-South is wider, use those extremes
            total_weight = northmost['rssi_max'] + southmost['rssi_max']
            center_lat = (northmost['lat'] * northmost['rssi_max'] + southmost['lat'] * southmost['rssi_max']) / total_weight
            # For longitude, use weighted average of all strong signals
            center_lon = sum(p['lon'] * p['rssi_max'] for p in strong_signals) / sum(p['rssi_max'] for p in strong_signals)
        else:
            # East-West is wider, use those extremes
            total_weight = eastmost['rssi_max'] + westmost['rssi_max']
            center_lon = (eastmost['lon'] * eastmost['rssi_max'] + westmost['lon'] * westmost['rssi_max']) / total_weight
            # For latitude, use weighted average of all strong signals
            center_lat = sum(p['lat'] * p['rssi_max'] for p in strong_signals) / sum(p['rssi_max'] for p in strong_signals)
        
        return {
            'lat': center_lat,
            'lon': center_lon,
            'ns_span': ns_span,
            'ew_span': ew_span,
            'confidence': len(strong_signals)
        }
    
    def calculate_color(self, rssi_above_threshold):
        """
        Calculate color based on how far above threshold.
        Green (best) -> Yellow -> Orange -> Red (at threshold)
        """
        if rssi_above_threshold >= 20:
            return '#00FF00'  # Bright green - excellent signal
        elif rssi_above_threshold >= 15:
            return '#7FFF00'  # Green-yellow
        elif rssi_above_threshold >= 10:
            return '#FFFF00'  # Yellow
        elif rssi_above_threshold >= 5:
            return '#FFA500'  # Orange
        else:
            return '#FF4500'  # Red-orange - just above threshold
    
    def calculate_radius(self, sample_count):
        """
        Calculate circle radius based on signal duration (sample count).
        More samples = longer signal = larger circle.
        """
        # Base radius of 5, scale up with count
        # Logarithmic scaling to prevent huge circles
        import math
        base_radius = 8
        scale_factor = 3
        return base_radius + scale_factor * math.log10(max(1, sample_count))
    
    def display_map_multi(self, file_datasets, combined_origin):
        """Generate HTML map with multiple datasets, each with their own colors and origins"""
        if not file_datasets:
            self.show_empty_map()
            return
        
        # Collect all points for centering
        all_points = []
        for dataset in file_datasets:
            all_points.extend(dataset['points'])
        
        center_lat = sum(p['lat'] for p in all_points) / len(all_points)
        center_lon = sum(p['lon'] for p in all_points) / len(all_points)
        
        # Prepare signal points as JSON
        signal_points_json = []
        for point in all_points:
            signal_points_json.append({
                'lat': point['lat'],
                'lon': point['lon'],
                'rssi_max': point['rssi_max'],
                'rssi_avg': point['rssi_avg'],
                'duration': point['duration'],
                'color': point['color'],
                'radius': point['radius'],
                'dataset_color': point['dataset_color'],
                'dataset_name': point['dataset_name']
            })
        
        # Prepare origins as JSON (individual file origins + combined)
        origins_json = []
        for dataset in file_datasets:
            if dataset['origin']:
                origins_json.append({
                    'lat': dataset['origin']['lat'],
                    'lon': dataset['origin']['lon'],
                    'confidence': dataset['origin']['confidence'],
                    'color': dataset['color'],
                    'name': dataset['filename'],
                    'type': 'individual'
                })
        
        # Add combined origin
        if combined_origin:
            origins_json.append({
                'lat': combined_origin['lat'],
                'lon': combined_origin['lon'],
                'confidence': combined_origin['confidence'],
                'color': '#FF0000',
                'name': 'Combined',
                'type': 'combined'
            })
        
        import json
        signal_points_str = json.dumps(signal_points_json)
        origins_str = json.dumps(origins_json)
        # Prepare leaflet.heat data if available
        heat_data_js = ''
        if self.show_heatmap and self.heatmap_points:
            # heatmap expects [lat, lon, intensity]
            heat_js_array = json.dumps(self.heatmap_points)
            # Prepare gradient maps (simple approximations)
            gradients = {
                'Inferno': {
                    0.0: '#000004', 0.25: '#3b0f70', 0.5: '#cc4778', 0.75: '#f89441', 1.0: '#fcffa4'
                },
                'Viridis': {
                    0.0: '#440154', 0.25: '#31688e', 0.5: '#35b779', 0.75: '#fde725', 1.0: '#fde725'
                },
                'Yellow-Red': {
                    0.0: '#FFFF66', 0.5: '#FFA500', 1.0: '#FF4500'
                }
            }
            sel_grad = gradients.get(self.heatmap_palette, gradients['Inferno'])
            # JSON-encode gradient for JS (object with numeric keys)
            grad_items = []
            for k, v in sel_grad.items():
                grad_items.append(f"{k}: '{v}'")
            grad_js = '{' + ','.join(grad_items) + '}'
            radius = int(self.heatmap_radius)
            blur = max(1, int(radius * 0.6))
            opacity = float(self.heatmap_opacity)
            heat_data_js = f"\n                var heatData = {heat_js_array};\n                var heatDataScaled = heatData.map(function(p) {{ return [p[0], p[1], Math.min(1.0, p[2]*{opacity})]; }});\n                var heat = L.heatLayer(heatDataScaled, {{radius: {radius}, blur: {blur}, gradient: {grad_js}, maxZoom: 17, max: 1.0}}).addTo(map);\n"
        
        # Generate HTML with Leaflet map
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>Signal Analysis</title>
            <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
            <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
            <style>
                body {{ margin: 0; padding: 0; }}
                #map {{ width: 100%; height: 100vh; }}
            </style>
        </head>
        <body>
            <div id="map"></div>
            <script>
                var map = L.map('map').setView([{center_lat}, {center_lon}], 16);
                
                L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
                    attribution: '© OpenStreetMap contributors',
                    maxZoom: 19
                }}).addTo(map);
                
                // Include heat layer if requested (leaflet.heat)
                (function() {{
                    var script = document.createElement('script');
                    script.src = 'https://unpkg.com/leaflet.heat/dist/leaflet-heat.js';
                    script.onload = function() {{
                        try {{
                            {heat_data_js}
                        }} catch(e) {{ console.log('heat init error', e); }}
                    }};
                    document.head.appendChild(script);
                }})();
                
                // Add signal points with signal strength colors
                var points = {signal_points_str};
                
                points.forEach(function(point) {{
                    var circle = L.circle([point.lat, point.lon], {{
                        color: point.color,
                        fillColor: point.color,
                        fillOpacity: 0.6,
                        radius: point.radius,
                        weight: 2
                    }}).addTo(map);
                    
                    circle.bindPopup(
                        '<b>Signal Details</b><br>' +
                        'Dataset: ' + point.dataset_name + '<br>' +
                        'Max RSSI: ' + point.rssi_max.toFixed(1) + ' dBm<br>' +
                        'Avg RSSI: ' + point.rssi_avg.toFixed(1) + ' dBm<br>' +
                        'Duration: ' + point.duration + ' samples<br>' +
                        'Location: ' + point.lat.toFixed(6) + ', ' + point.lon.toFixed(6)
                    );
                }});
                
                // Add origin markers with unique colors
                var origins = {origins_str};
                
                origins.forEach(function(origin) {{
                    // Add confidence radius circle for combined origin (2 miles = 3218.688 meters)
                    if (origin.type === 'combined') {{
                        var confidenceCircle = L.circle([origin.lat, origin.lon], {{
                            color: '#8B0000',
                            fillColor: '#8B0000',
                            fillOpacity: 0.1,
                            weight: 2,
                            dashArray: '5, 10',
                            radius: 3218.688
                        }}).addTo(map);
                        
                        confidenceCircle.bindPopup(
                            '<b>2 Mile Confidence Radius</b><br>' +
                            'Estimated signal origin area'
                        );
                    }}
                    
                    var iconSvg = origin.type === 'combined' 
                        ? '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 40 40"><circle cx="20" cy="20" r="12" fill="#8B0000" stroke="white" stroke-width="3"/><circle cx="20" cy="20" r="5" fill="white"/><circle cx="20" cy="20" r="2" fill="#8B0000"/></svg>'
                        : '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32"><circle cx="16" cy="16" r="8" fill="' + origin.color + '" stroke="white" stroke-width="2"/><circle cx="16" cy="16" r="3" fill="white"/></svg>';
                    
                    var iconSize = origin.type === 'combined' ? [40, 40] : [32, 32];
                    var iconAnchor = origin.type === 'combined' ? [20, 20] : [16, 16];
                    
                    var originIcon = L.icon({{
                        iconUrl: 'data:image/svg+xml;base64,' + btoa(iconSvg),
                        iconSize: iconSize,
                        iconAnchor: iconAnchor,
                        popupAnchor: [0, -iconAnchor[1]]
                    }});
                    
                    var marker = L.marker([origin.lat, origin.lon], {{ icon: originIcon }}).addTo(map);
                    marker.bindPopup(
                        '<b>' + (origin.type === 'combined' ? 'Combined Origin Estimate' : 'Origin Estimate') + '</b><br>' +
                        'Dataset: ' + origin.name + '<br>' +
                        'Location: ' + origin.lat.toFixed(6) + ', ' + origin.lon.toFixed(6) + '<br>' +
                        'Based on ' + origin.confidence + ' detection points'
                    );
                }});
                
                // Fit map to show all points and origins
                if (points.length > 0) {{
                    var bounds = L.latLngBounds(points.map(p => [p.lat, p.lon]));
                    origins.forEach(function(origin) {{
                        bounds.extend([origin.lat, origin.lon]);
                    }});
                    map.fitBounds(bounds, {{ padding: [50, 50] }});
                }}
                
            </script>
        </body>
        </html>
        """
        
        self.web_view.setHtml(html)
        for widget in self.dataset_checkbox_widgets:
            widget.raise_()

    def toggle_heatmap(self, state):
        """Toggle heatmap on/off and re-render map."""
        self.show_heatmap = (state == 2)
        # Re-render current visible datasets
        visible_datasets = []
        for idx, dataset in enumerate(self.file_datasets):
            if self.dataset_checkboxes[idx].isChecked():
                visible_datasets.append(dataset)

        show_combined = True
        if len(self.dataset_checkboxes) > len(self.file_datasets):
            show_combined = self.dataset_checkboxes[-1].isChecked()

        combined_origin = None
        if visible_datasets and show_combined:
            all_visible_points = []
            for dataset in visible_datasets:
                all_visible_points.extend(dataset['points'])
            combined_origin = self.estimate_signal_origin(all_visible_points)

        self.display_map_multi(visible_datasets, combined_origin)
    
    def display_map(self, signal_points, origin=None):
        """Generate HTML map with signal visualization and estimated origin"""
        if not signal_points:
            self.show_empty_map()
            return
        
        # Calculate map center (average of all points)
        center_lat = sum(p['lat'] for p in signal_points) / len(signal_points)
        center_lon = sum(p['lon'] for p in signal_points) / len(signal_points)
        
        # Prepare origin data for JavaScript
        origin_js = 'null'
        if origin:
            origin_js = f'{{"lat": {origin["lat"]}, "lon": {origin["lon"]}, "confidence": {origin["confidence"]}}}'
        
        # Generate HTML with Leaflet map
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>Signal Analysis</title>
            <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
            <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
            <style>
                body {{ margin: 0; padding: 0; }}
                #map {{ width: 100%; height: 100vh; }}
            </style>
        </head>
        <body>
            <div id="map"></div>
            <script>
                var map = L.map('map').setView([{center_lat}, {center_lon}], 16);
                
                L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
                    attribution: '© OpenStreetMap contributors',
                    maxZoom: 19
                }}).addTo(map);
                
                // Add signal points
                var points = {signal_points};
                
                points.forEach(function(point) {{
                    var circle = L.circle([point.lat, point.lon], {{
                        color: point.color,
                        fillColor: point.color,
                        fillOpacity: 0.6,
                        radius: point.radius
                    }}).addTo(map);
                    
                    circle.bindPopup(
                        '<b>Signal Details</b><br>' +
                        'Max RSSI: ' + point.rssi_max.toFixed(1) + ' dBm<br>' +
                        'Avg RSSI: ' + point.rssi_avg.toFixed(1) + ' dBm<br>' +
                        'Duration: ' + point.duration + ' samples<br>' +
                        'Location: ' + point.lat.toFixed(6) + ', ' + point.lon.toFixed(6)
                    );
                }});
                
                // Add estimated origin marker
                var origin = {origin_js};
                if (origin) {{
                    var originIcon = L.icon({{
                        iconUrl: 'data:image/svg+xml;base64,' + btoa('<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32"><circle cx="16" cy="16" r="8" fill="red" stroke="white" stroke-width="2"/><circle cx="16" cy="16" r="3" fill="white"/></svg>'),
                        iconSize: [32, 32],
                        iconAnchor: [16, 16],
                        popupAnchor: [0, -16]
                    }});
                    
                    var marker = L.marker([origin.lat, origin.lon], {{ icon: originIcon }}).addTo(map);
                    marker.bindPopup(
                        '<b>Estimated Signal Origin</b><br>' +
                        'Location: ' + origin.lat.toFixed(6) + ', ' + origin.lon.toFixed(6) + '<br>' +
                        'Based on ' + origin.confidence + ' detection points'
                    );
                }}
                
                // Fit map to show all points
                if (points.length > 0) {{
                    var bounds = L.latLngBounds(points.map(p => [p.lat, p.lon]));
                    if (origin) {{
                        bounds.extend([origin.lat, origin.lon]);
                    }}
                    map.fitBounds(bounds, {{ padding: [50, 50] }});
                }}
            </script>
        </body>
        </html>
        """
        
        self.web_view.setHtml(html)
        for widget in self.dataset_checkbox_widgets:
            widget.raise_()
    
    def show_empty_map(self):
        """Show empty map with default view"""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>Signal Analysis</title>
            <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
            <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
            <style>
                body { margin: 0; padding: 0; }
                #map { width: 100%; height: 100vh; }
            </style>
        </head>
        <body>
            <div id="map"></div>
            <script>
                var map = L.map('map').setView([51.505, -0.09], 13);
                
                L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                    attribution: '© OpenStreetMap contributors',
                    maxZoom: 19
                }).addTo(map);
            </script>
        </body>
        </html>
        """
        self.web_view.setHtml(html)
        for widget in self.dataset_checkbox_widgets:
            widget.raise_()
    
    def resizeEvent(self, event):
        """Handle window resize to reposition checkboxes"""
        super().resizeEvent(event)
        if self.dataset_checkbox_widgets:
            self.position_checkboxes()

