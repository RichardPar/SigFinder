"""PyQt6 GUI for SigFinder.

This module creates a Qt window with a QWebEngineView showing the Leaflet map HTML.
It polls `get_position_callable()` on a timer and calls the same JS `update_marker(lat, lon)`
function in the page to move the pin.
"""
from PyQt6 import QtWidgets, QtCore, QtGui
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEnginePage
import sys
import tempfile
import os

from .analysis_window import AnalysisWindow

HTML = None
try:
    from .gui import HTML_TEMPLATE
    HTML = HTML_TEMPLATE
    try:
        from .gui import HTML_GRAPH_TEMPLATE
    except Exception:
        HTML_GRAPH_TEMPLATE = None
except Exception:
    HTML = """<!doctype html><html><body><h1>Map</h1></body></html>"""
    HTML_GRAPH_TEMPLATE = None


class DebugWebEnginePage(QWebEnginePage):
    """Custom QWebEnginePage that prints JavaScript console messages"""
    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        print(f'JS Console [{level}] {sourceID}:{lineNumber}: {message}')


def _write_tmp(html: str) -> str:
    td = tempfile.mkdtemp(prefix='sigfinder_qt_')
    path = os.path.join(td, 'map.html')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)
    return path


def _write_tmp_graph(html: str) -> str:
    td = tempfile.mkdtemp(prefix='sigfinder_qt_graph_')
    path = os.path.join(td, 'graph.html')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)
    return path


class MapWindow(QtWidgets.QMainWindow):
    def __init__(self, get_position_callable, get_status_callable=None, initial_range_default=-110.0):
        super().__init__()
        self.get_pos = get_position_callable
        self.get_status = get_status_callable
        self._initial_range_default = initial_range_default
        self.setWindowTitle('SigFinder Map (Qt)')
        self.resize(1000, 700)
        
        # CSV logging
        self.csv_file = None
        self.csv_writer = None
        self.rssi_log_callback = None
        self.session_paused = False  # Session pause state
        
        # Triggered markers tracking
        self.triggered_markers = []  # List of (lat, lon) tuples
        self.range_trigger_value = initial_range_default  # Current RSSI trigger threshold
        self.last_triggered_state = False  # Track if we were in triggered state

        # Create menu bar
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu('&File')
        
        new_session_action = QtGui.QAction('&New Session...', self)
        new_session_action.setShortcut('Ctrl+N')
        new_session_action.setStatusTip('Start new logging session')
        new_session_action.triggered.connect(lambda: self.start_new_session())
        file_menu.addAction(new_session_action)
        
        self.stop_session_action = QtGui.QAction('&Stop Session', self)
        self.stop_session_action.setShortcut('Ctrl+S')
        self.stop_session_action.setStatusTip('Stop current logging session')
        self.stop_session_action.triggered.connect(lambda: self.stop_session())
        self.stop_session_action.setEnabled(False)  # Disabled until session starts
        file_menu.addAction(self.stop_session_action)
        
        file_menu.addSeparator()
        
        self.pause_session_action = QtGui.QAction('Session &Pause', self)
        self.pause_session_action.setShortcut('Ctrl+P')
        self.pause_session_action.setStatusTip('Pause/resume CSV logging')
        self.pause_session_action.setCheckable(True)
        self.pause_session_action.setChecked(False)
        self.pause_session_action.setEnabled(False)  # Disabled until session starts
        self.pause_session_action.triggered.connect(lambda: self.toggle_session_pause())
        file_menu.addAction(self.pause_session_action)
        
        file_menu.addSeparator()
        
        exit_action = QtGui.QAction('E&xit', self)
        exit_action.setShortcut('Ctrl+Q')
        exit_action.setStatusTip('Exit application')
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # View menu
        view_menu = menubar.addMenu('&View')
        
        center_action = QtGui.QAction('&Center on GPS', self)
        center_action.setShortcut('Ctrl+L')
        center_action.setStatusTip('Center map on current GPS position')
        center_action.triggered.connect(lambda: self.center_on_gps())
        view_menu.addAction(center_action)
        
        view_menu.addSeparator()
        
        self.toggle_rssi_action = QtGui.QAction('Show &RSSI Graph', self)
        self.toggle_rssi_action.setShortcut('Ctrl+R')
        self.toggle_rssi_action.setStatusTip('Toggle RSSI graph window')
        self.toggle_rssi_action.setCheckable(True)
        self.toggle_rssi_action.setChecked(False)
        self.toggle_rssi_action.triggered.connect(lambda: self.toggle_rssi_window())
        view_menu.addAction(self.toggle_rssi_action)
        
        # Settings menu
        settings_menu = menubar.addMenu('&Settings')
        
        range_action = QtGui.QAction('&Range Trigger...', self)
        range_action.setStatusTip('Configure RSSI range trigger')
        range_action.triggered.connect(lambda: self.show_range_dialog())
        settings_menu.addAction(range_action)
        
        settings_menu.addSeparator()
        
        clear_markers_action = QtGui.QAction('&Clear All Markers', self)
        clear_markers_action.setStatusTip('Remove all triggered markers from map')
        clear_markers_action.triggered.connect(lambda: self.clear_all_markers())
        settings_menu.addAction(clear_markers_action)
        
        # Analyse menu
        analyse_menu = menubar.addMenu('&Analyse')
        
        analyse_action = QtGui.QAction('&Signal Analysis...', self)
        analyse_action.setShortcut('Ctrl+A')
        analyse_action.setStatusTip('Analyse current session data')
        analyse_action.triggered.connect(lambda: self.show_analysis_window())
        analyse_menu.addAction(analyse_action)
        
        # Help menu
        help_menu = menubar.addMenu('&Help')
        
        about_action = QtGui.QAction('&About', self)
        about_action.setStatusTip('About SigFinder')
        about_action.triggered.connect(lambda: self.show_about())
        help_menu.addAction(about_action)

        # Web view
        self.view = QWebEngineView()
        
        # Use custom page to capture console messages
        custom_page = DebugWebEnginePage(self.view)
        self.view.setPage(custom_page)
        
        # Enable developer tools console output
        from PyQt6.QtWebEngineCore import QWebEngineSettings
        settings = self.view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        
        # Enable developer tools (F12 to open)
        try:
            import os
            if os.environ.get('QTWEBENGINE_REMOTE_DEBUGGING'):
                print(f"qt-gui: Remote debugging enabled on port {os.environ.get('QTWEBENGINE_REMOTE_DEBUGGING')}")
        except:
            pass
        
        self.setCentralWidget(self.view)
        
        # RSSI graph window reference (will be set by start_gui)
        self.rssi_window = None

        path = _write_tmp(HTML)
        print(f'qt-gui: Loading HTML from: {path}')
        print(f'qt-gui: HTML content length: {len(HTML) if HTML else 0} bytes')
        url = QtCore.QUrl.fromLocalFile(path)
        print(f'qt-gui: Loading URL: {url.toString()}')
        
        # Connect to page load errors
        self.view.loadFinished.connect(lambda ok: print(f'qt-gui: Page load finished, success={ok}'))
        
        self.view.load(url)
        # initialize range value in page after load
        try:
            def _init(js_ok):
                print(f'qt-gui: loadFinished signal received, js_ok={js_ok}')
                try:
                    v = float(self._initial_range_default)
                except Exception:
                    v = -110.0
                js = f"try{{var el=document.getElementById('range_trigger'); if(el) el.value = {v}; RANGE_TRIGGER = {v}; console.log('range init', {v});}}catch(e){{console.log('range init error', e);}}"
                try:
                    self.view.page().runJavaScript(js)
                except Exception:
                    pass
            self.view.loadFinished.connect(_init)
        except Exception:
            pass

        # Timer to poll position
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.update_marker)
        # give the page a second to load before starting
        QtCore.QTimer.singleShot(1000, self.timer.start)

    def on_btn(self, n: int):
        try:
            if n == 4:
                self.center_on_gps()
                return
        except Exception:
            pass
        QtWidgets.QMessageBox.information(self, 'Button', f'Button {n} pressed (placeholder)')

    def center_on_gps(self):
        """Center map on current GPS position"""
        try:
            lat, lon = self.get_pos()
            if lat is None or lon is None:
                QtWidgets.QMessageBox.information(self, 'Center on GPS', 'No GPS fix available.')
                return
            js = f'window.map.setView([{float(lat):.8f}, {float(lon):.8f}], 14)'
            self.view.page().runJavaScript(js)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, 'Error', f'Failed to center map: {e}')
    
    def toggle_rssi_window(self):
        """Toggle RSSI graph window visibility"""
        if self.rssi_window is None:
            QtWidgets.QMessageBox.warning(self, 'RSSI Graph', 'RSSI graph window not available.')
            self.toggle_rssi_action.setChecked(False)
            return
        
        if self.rssi_window.isVisible():
            self.rssi_window.hide()
            self.toggle_rssi_action.setChecked(False)
        else:
            self.rssi_window.show()
            self.toggle_rssi_action.setChecked(True)

    def show_range_dialog(self):
        """Show dialog to configure range trigger"""
        value, ok = QtWidgets.QInputDialog.getDouble(
            self, 'Range Trigger', 'Set RSSI range trigger (dBm):',
            self._initial_range_default, -200.0, 0.0, 1
        )
        if ok:
            self._initial_range_default = value
            self.range_trigger_value = value  # Update tracked value
            js = f"RANGE_TRIGGER = {float(value)}; var el=document.getElementById('range_trigger'); if(el) el.value = {float(value)}; console.log('Range trigger set to', {float(value)});"
            self.view.page().runJavaScript(js)
    
    def clear_all_markers(self):
        """Clear all triggered markers from the map"""
        if not self.triggered_markers:
            QtWidgets.QMessageBox.information(
                self, 'Clear Markers',
                'No triggered markers to clear.'
            )
            return
        
        count = len(self.triggered_markers)
        reply = QtWidgets.QMessageBox.question(
            self, 'Clear Markers',
            f'Clear {count} triggered marker(s) from the map?',
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No
        )
        
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            # Clear the list
            self.triggered_markers.clear()
            
            # Remove markers from map via JavaScript
            js = '''(function() {
                if (window.triggeredMarkers) {
                    window.triggeredMarkers.forEach(function(marker) {
                        window.map.removeLayer(marker);
                    });
                    window.triggeredMarkers = [];
                    console.log('All triggered markers cleared');
                }
            })();'''
            
            self.view.page().runJavaScript(js)
            self.statusBar().showMessage(f'Cleared {count} triggered marker(s)', 5000)
            print(f'qt-gui: Cleared {count} triggered markers')

    def show_analysis_window(self):
        """Show signal analysis window"""
        # Get current CSV file path if session is active
        current_file = None
        if self.csv_file:
            try:
                current_file = self.csv_file.name
            except:
                pass
        
        # Create and show analysis window
        analysis_window = AnalysisWindow(parent=self, current_csv_file=current_file)
        analysis_window.show()

    def show_about(self):
        """Show about dialog"""
        from sigfinder import __version__
        QtWidgets.QMessageBox.about(
            self, 'About SigFinder',
            f'''<h2>SigFinder</h2>
            <p><b>Version:</b> {__version__}</p>
            <hr>
            <p><b>Description:</b><br>
            GPS-based signal strength mapping and analysis tool for radio frequency signal hunting.</p>
            <p><b>Supported Hardware:</b></p>
            <ul>
            <li>ADALM-Pluto SDR</li>
            <li>SDRplay (RSP series)</li>
            <li>RTL-SDR</li>
            </ul>
            <p><b>Features:</b></p>
            <ul>
            <li>Real-time GPS tracking and signal mapping</li>
            <li>Automatic triggered markers (50m spacing)</li>
            <li>CSV logging with pause/resume</li>
            <li>Advanced signal analysis and origin estimation</li>
            <li>Multi-dataset comparison</li>
            <li>Outlier detection and oscillation filtering</li>
            </ul>
            <hr>
            <p><small>&copy; 2025 - Licensed under open source</small></p>
            '''
        )

    def start_new_session(self):
        """Start a new CSV logging session"""
        from datetime import datetime
        import csv
        import os
        
        # Generate default filename with current date and time
        default_name = datetime.now().strftime('%Y-%m-%d_%H-%M-%S.csv')
        
        # Show save file dialog
        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            'New Logging Session',
            default_name,
            'CSV Files (*.csv);;All Files (*)'
        )
        
        if not file_path:
            return  # User cancelled
        
        # Close existing file if open
        if self.csv_file:
            try:
                self.csv_file.close()
            except:
                pass
        
        # Open new CSV file
        try:
            self.csv_file = open(file_path, 'w', newline='', encoding='utf-8')
            self.csv_writer = csv.writer(self.csv_file)
            
            # Write header
            self.csv_writer.writerow([
                'Timestamp', 'Latitude', 'Longitude', 'Fix Quality', 
                'Num Satellites', 'RMC Status', 'RSSI (dBm)'
            ])
            self.csv_file.flush()
            
            print(f'qt-gui: Started logging session to {file_path}')
            self.setWindowTitle(f'SigFinder Map (Qt) - Logging to {os.path.basename(file_path)}')
            self.stop_session_action.setEnabled(True)  # Enable stop button
            self.pause_session_action.setEnabled(True)  # Enable pause checkbox
            self.pause_session_action.setChecked(False)  # Default to not paused
            self.session_paused = False
            QtWidgets.QMessageBox.information(
                self, 'Session Started',
                f'Logging to: {os.path.basename(file_path)}'
            )
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, 'Error',
                f'Failed to create log file: {e}'
            )

    def stop_session(self):
        """Stop current logging session"""
        if not self.csv_file:
            return
        
        try:
            self.csv_file.close()
            print("qt-gui: Logging session stopped")
            self.csv_file = None
            self.csv_writer = None
            self.stop_session_action.setEnabled(False)
            self.pause_session_action.setEnabled(False)
            self.pause_session_action.setChecked(False)
            self.session_paused = False
            self.setWindowTitle('SigFinder Map (Qt)')
            QtWidgets.QMessageBox.information(
                self, 'Session Stopped',
                'Logging session stopped successfully.'
            )
        except Exception as e:
            QtWidgets.QMessageBox.warning(
                self, 'Error',
                f'Error stopping session: {e}'
            )

    def set_rssi_log_callback(self, callback):
        """Set callback to be called on each RSSI sample"""
        self.rssi_log_callback = callback
    
    def toggle_session_pause(self):
        """Toggle session pause state"""
        self.session_paused = self.pause_session_action.isChecked()
        if self.session_paused:
            self.statusBar().showMessage('Session paused - not writing to CSV', 5000)
        else:
            self.statusBar().showMessage('Session resumed - writing to CSV', 5000)
    
    def calculate_distance(self, lat1, lon1, lat2, lon2):
        """Calculate distance between two coordinates in meters using Haversine formula"""
        import math
        R = 6371000  # Earth's radius in meters
        
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        delta_lat = math.radians(lat2 - lat1)
        delta_lon = math.radians(lon2 - lon1)
        
        a = math.sin(delta_lat/2) * math.sin(delta_lat/2) + \
            math.cos(lat1_rad) * math.cos(lat2_rad) * \
            math.sin(delta_lon/2) * math.sin(delta_lon/2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        
        return R * c
    
    def add_triggered_marker(self, lat, lon, rssi_dbm):
        """Add a marker at the triggered position if it's more than 50m from nearest marker"""
        if lat is None or lon is None:
            return
        
        # Check distance to all existing markers
        min_distance = 50  # meters
        for marker_lat, marker_lon in self.triggered_markers:
            distance = self.calculate_distance(lat, lon, marker_lat, marker_lon)
            if distance < min_distance:
                print(f'qt-gui: Skipping triggered marker - only {distance:.1f}m from nearest marker')
                return
        
        # Add new marker
        self.triggered_markers.append((lat, lon))
        print(f'qt-gui: Adding triggered marker at {lat:.6f}, {lon:.6f} (RSSI: {rssi_dbm:.1f} dBm)')
        
        # Send JavaScript to add marker to map
        js = f'''(function() {{
            if (!window.triggeredMarkers) {{
                window.triggeredMarkers = [];
            }}
            var marker = L.circleMarker([{float(lat):.8f}, {float(lon):.8f}], {{
                radius: 10,
                color: '#FF0000',
                fillColor: '#FF4444',
                fillOpacity: 0.8,
                weight: 2
            }}).addTo(window.map);
            marker.bindPopup('Triggered: {rssi_dbm:.1f} dBm<br>Lat: {lat:.6f}<br>Lon: {lon:.6f}');
            window.triggeredMarkers.push(marker);
            console.log('Added triggered marker at', {float(lat):.8f}, {float(lon):.8f});
        }})();'''
        
        self.view.page().runJavaScript(js)
    
    def log_data(self, lat, lon, status):
        """Log GPS and signal data to CSV"""
        if not self.csv_writer or self.session_paused:
            return
        
        try:
            from datetime import datetime
            
            timestamp = datetime.now().isoformat()
            self.csv_writer.writerow([
                timestamp,
                lat if lat is not None else '',
                lon if lon is not None else '',
                status.get('fix_quality', ''),
                status.get('num_sats', ''),
                status.get('rmc_status', ''),
                status.get('rssi_dbm', '')
            ])
            self.csv_file.flush()
        except Exception as e:
            print(f'qt-gui: Error logging data: {e}')
    
    def log_rssi_sample(self, rssi_dbm):
        """Log single RSSI sample with current GPS position (called per RSSI sample)"""
        if not self.csv_writer or self.session_paused:
            return
        
        try:
            from datetime import datetime
            lat, lon = self.get_pos()
            status = self.get_status() if self.get_status else {}
            
            timestamp = datetime.now().isoformat()
            self.csv_writer.writerow([
                timestamp,
                lat if lat is not None else '',
                lon if lon is not None else '',
                status.get('fix_quality', ''),
                status.get('num_sats', ''),
                status.get('rmc_status', ''),
                rssi_dbm if rssi_dbm is not None else ''
            ])
            self.csv_file.flush()
        except Exception as e:
            print(f'qt-gui: Error logging RSSI sample: {e}')

    def update_marker(self):
        try:
            lat, lon = self.get_pos()
            # Debug-print what we will send to the page
            print('qt-gui: update_marker called with', (lat, lon))
            if lat is None or lon is None:
                js = 'update_marker(null, null)'
            else:
                # ensure numbers
                js = f'update_marker({float(lat):.8f}, {float(lon):.8f})'
            print(f'qt-gui: executing JS: {js}')
            self.view.page().runJavaScript(js, lambda result: print(f'qt-gui: update_marker result: {result}'))
            
            # also update status if available
            if self.get_status is not None:
                st = self.get_status()
                print('qt-gui: sending status ->', st)
                
                # Check if RSSI exceeds trigger threshold
                rssi_dbm = st.get('rssi_dbm')
                if rssi_dbm is not None and lat is not None and lon is not None:
                    try:
                        if rssi_dbm >= self.range_trigger_value:
                            # Only add marker on rising edge (when we first exceed threshold)
                            if not self.last_triggered_state:
                                self.add_triggered_marker(lat, lon, rssi_dbm)
                                self.last_triggered_state = True
                        else:
                            self.last_triggered_state = False
                    except Exception as e:
                        print(f'qt-gui: Error checking RSSI trigger: {e}')
                
                import json
                status_js = f'update_status({json.dumps(st)})'
                print(f'qt-gui: executing JS: update_status(...)')
                self.view.page().runJavaScript(status_js, lambda result: print(f'qt-gui: update_status result: {result}'))
        except Exception as e:
            print(f'qt-gui: update_marker exception: {e}')
            import traceback
            traceback.print_exc()

    def closeEvent(self, event):
        """Handle window close event - exit the application"""
        # Close CSV file if open
        if self.csv_file:
            try:
                self.csv_file.close()
                print("qt-gui: CSV log file closed")
            except:
                pass
        
        print("qt-gui: Map window closed, exiting application")
        QtWidgets.QApplication.quit()
        event.accept()


class GraphWindow(QtWidgets.QMainWindow):
    def __init__(self, get_status_callable, parent=None):
        super().__init__(parent)
        self.get_status = get_status_callable
        self.setWindowTitle('RSSI Graph (Qt)')
        self.resize(640, 380)
        self.view = QWebEngineView()
        self.setCentralWidget(self.view)
        html = HTML_GRAPH_TEMPLATE if HTML_GRAPH_TEMPLATE is not None else """<!doctype html><html><body><h1>RSSI</h1></body></html>"""
        path = _write_tmp_graph(html)
        self.view.load(QtCore.QUrl.fromLocalFile(path))
        # Timer to poll status
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.update_graph)
        QtCore.QTimer.singleShot(1000, self.timer.start)
    
    def closeEvent(self, event):
        """Handle window close event - update parent menu state"""
        if self.parent() and hasattr(self.parent(), 'toggle_rssi_action'):
            self.parent().toggle_rssi_action.setChecked(False)
        event.accept()


    def update_graph(self):
        try:
            if self.get_status is None:
                return
            st = self.get_status()
            # prefer last raw-sample dBm for the graph (not averaged)
            r = st.get('rssi_last_dbm', None)
            import json
            self.view.page().runJavaScript(f'update_rssi_graph({json.dumps(r)})')
        except Exception:
            pass


def start_gui(get_position_callable, get_status_callable=None, get_signal_events_callable=None, initial_range_default=-110.0, config_save_callback=None, rssi_callback_setter=None):
    print("qt-gui: starting PyQt GUI")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    
    # Enable Ctrl+C to terminate the application
    import signal
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    
    # Create a timer to allow Python to process signals
    timer = QtCore.QTimer()
    timer.timeout.connect(lambda: None)  # Wake up Python interpreter
    timer.start(100)  # Check every 100ms
    
    win = MapWindow(get_position_callable, get_status_callable, initial_range_default)
    
    # Register RSSI logging callback with main thread if setter provided
    if rssi_callback_setter:
        rssi_callback_setter(win.log_rssi_sample)
    
    win.show()
    # show graph window if HTML_GRAPH_TEMPLATE is available
    graph_win = None
    if HTML_GRAPH_TEMPLATE is not None:
        graph_win = GraphWindow(get_status_callable, parent=win)
        graph_win.show()
        # Store reference in main window for toggle control
        win.rssi_window = graph_win
        # Set initial menu state
        win.toggle_rssi_action.setChecked(True)
    
    # Return window reference before blocking on exec
    # Store reference to be accessed after exec returns
    app._sigfinder_window = win
    app.exec()


if __name__ == '__main__':
    # quick smoke test
    def gp():
        return 51.5074, -0.1278

    start_gui(gp)
