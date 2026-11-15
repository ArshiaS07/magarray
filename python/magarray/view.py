"""Live viewer: a grid per board and a time plot of the selected sensor. It only reads."""

from __future__ import annotations

import math
import time

import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtWidgets

from .monitor import BoardMonitor
from .source import ReplaySource, SerialSource

MODES = ("|B| raw", "|B − tare|", "noise, 2 s", "peak |count|")
STALE_S = 0.5
NOISE_S = 2.0
TARE_S = 2.0

pg.setConfigOptions(imageAxisOrder="row-major", antialias=True)


def grid_shape(n: int) -> tuple[int, int]:
    """Rows and columns to draw n sensors in: square when n is a square (25 → 5 × 5), else one row."""
    r = math.isqrt(n)
    return (r, r) if r * r == n else (1, n)


class BoardGrid(pg.GraphicsLayoutWidget):
    """One board's sensors as cells, ids row-major from the top left (assumed, not verified)."""

    sensor_clicked = QtCore.Signal(object, int)

    def __init__(self, key, monitor: BoardMonitor) -> None:
        super().__init__()
        self.key, self.monitor = key, monitor
        self.rows, self.cols = grid_shape(monitor.n)
        channel, board_id = key
        where = "direct" if channel is None else f"channel {channel}"
        self.plot = self.addPlot(title=f"board {board_id} · {where}")
        self.plot.hideAxis("left"), self.plot.hideAxis("bottom")
        self.plot.invertY(True)
        self.plot.setAspectLocked(True)
        self.plot.setMouseEnabled(False, False)
        self.plot.hideButtons()
        self.image = pg.ImageItem(np.zeros((self.rows, self.cols)))
        self.plot.addItem(self.image)
        self.bar = pg.ColorBarItem(values=(0, 1), colorMap="viridis", interactive=False, width=12)
        self.bar.setImageItem(self.image, insert_in=self.plot)
        self.flags = pg.ScatterPlotItem(pxMode=False, symbol="s", size=0.92, brush=None)
        self.selection = pg.ScatterPlotItem(
            pxMode=False,
            symbol="s",
            size=0.98,
            brush=None,
            pen=pg.mkPen("w", width=2, style=QtCore.Qt.PenStyle.DashLine),
        )
        self.plot.addItem(self.flags), self.plot.addItem(self.selection)
        self.labels = []
        for i in range(monitor.n):
            r, c = divmod(i, self.cols)
            t = pg.TextItem(anchor=(0.5, 0.5), color="w")
            t.setPos(c + 0.5, r + 0.5)
            self.plot.addItem(t)
            self.labels.append(t)
        self.scene().sigMouseClicked.connect(self._clicked)
        self.setMinimumSize(320, 280)

    def _clicked(self, ev) -> None:
        p = self.plot.vb.mapSceneToView(ev.scenePos())
        r, c = math.floor(p.y()), math.floor(p.x())
        if 0 <= r < self.rows and 0 <= c < self.cols and r * self.cols + c < self.monitor.n:
            self.sensor_clicked.emit(self.key, r * self.cols + c)

    def refresh(self, mode: str, selected: int | None, saturation: int) -> None:
        m = self.monitor
        latest = m.latest()
        if latest is None:
            return
        f = latest.astype(float)
        if mode == "|B| raw":
            v = np.linalg.norm(f, axis=1)
        elif mode == "|B − tare|":
            v = np.linalg.norm(f - m.tare, axis=1) if m.tare is not None else np.full(m.n, np.nan)
        elif mode == "noise, 2 s":
            v = m.noise(NOISE_S)
        else:
            v = m.peak_abs.astype(float)
        img = np.full(self.rows * self.cols, np.nan)
        img[: m.n] = v
        finite = v[np.isfinite(v)]
        lo, hi = (float(finite.min()), float(finite.max())) if len(finite) else (0.0, 1.0)
        self.image.setImage(img.reshape(self.rows, self.cols), autoLevels=False)
        self.bar.setLevels((lo, hi if hi > lo else lo + 1))
        for i, t in enumerate(self.labels):
            t.setText(f"{m.sensor_ids[i]}\n{v[i]:.0f}" if np.isfinite(v[i]) else f"{m.sensor_ids[i]}\n–")
        saturated = np.abs(latest.astype(np.int32)).max(axis=1) >= saturation
        stale = m.stale(STALE_S)
        spots = [{"pos": self._centre(i), "pen": pg.mkPen("r", width=4)} for i in np.flatnonzero(saturated)]
        spots += [
            {"pos": self._centre(i), "pen": pg.mkPen((255, 150, 0), width=4)}
            for i in np.flatnonzero(stale & ~saturated)
        ]
        self.flags.setData(spots)
        self.selection.setData([{"pos": self._centre(selected)}] if selected is not None else [])

    def _centre(self, i: int) -> tuple[float, float]:
        r, c = divmod(int(i), self.cols)
        return (c + 0.5, r + 0.5)


class Viewer(QtWidgets.QMainWindow):
    def __init__(self, source, saturation: int = 32000, window_s: float = 10.0) -> None:
        super().__init__()
        self.source, self.saturation, self.window_s = source, saturation, window_s
        self.monitors: dict = {}
        self.grids: dict = {}
        self.selected: tuple | None = None  # (board key, sensor index)
        self._last_scan_wall = None
        self.setWindowTitle(f"magarray: {source.status.description}")

        tools = self.addToolBar("view")
        self.mode = QtWidgets.QComboBox()
        self.mode.addItems(MODES)
        tools.addWidget(QtWidgets.QLabel(" cells: ")), tools.addWidget(self.mode)
        tools.addSeparator()
        tare = tools.addAction(f"Tare {TARE_S:.0f} s")
        tare.triggered.connect(self._tare)
        peaks = tools.addAction("Reset peaks")
        peaks.triggered.connect(lambda: [m.reset_peaks() for m in self.monitors.values()])
        tools.addSeparator()
        self.minus_tare = QtWidgets.QCheckBox("plot minus tare")
        tools.addWidget(self.minus_tare)

        self.boards = QtWidgets.QWidget()
        self.boards_layout = QtWidgets.QGridLayout(self.boards)
        self.waiting = QtWidgets.QLabel("waiting for frames …")
        self.boards_layout.addWidget(self.waiting, 0, 0)
        self.plots = pg.GraphicsLayoutWidget()
        self.title = self.plots.addLabel("", row=0, col=0)
        self.axes, self.curves = [], []
        for k, (name, colour) in enumerate((("x", "r"), ("y", "g"), ("z", "c"))):
            p = self.plots.addPlot(row=k + 1, col=0)  # one per axis, each scaled on its own
            p.showGrid(x=True, y=True, alpha=0.3)
            p.setLabel("left", f"{name}, counts")
            p.getAxis("left").enableAutoSIPrefix(False)
            p.getAxis("left").setWidth(70)
            if self.axes:
                p.setXLink(self.axes[0])
            self.axes.append(p)
            self.curves.append(p.plot(pen=pg.mkPen(colour, width=1.5)))
        self.axes[-1].setLabel("bottom", "board time − now", units="s")
        split = QtWidgets.QSplitter()
        split.addWidget(self.boards), split.addWidget(self.plots)
        split.setSizes([520, 760])
        self.setCentralWidget(split)
        self.status = QtWidgets.QLabel()
        self.statusBar().addWidget(self.status, 1)

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(50)

    def _tick(self) -> None:
        for scan in self.source.take():
            m = self.monitors.get(scan.key)
            if m is None:
                m = self.monitors[scan.key] = BoardMonitor(scan.sensor_ids, history_s=max(self.window_s, 10.0))
                self._add_grid(scan.key, m)
            m.add(scan)
            self._last_scan_wall = time.monotonic()
        mode = self.mode.currentText()
        for key, g in self.grids.items():
            g.refresh(mode, self.selected[1] if self.selected and self.selected[0] == key else None, self.saturation)
        self._refresh_plot()
        self._refresh_status()

    def _add_grid(self, key, monitor: BoardMonitor) -> None:
        if self.waiting is not None:
            self.waiting.deleteLater()
            self.waiting = None
        g = BoardGrid(key, monitor)
        g.sensor_clicked.connect(self._select)
        n = len(self.grids)
        self.boards_layout.addWidget(g, n // 2, n % 2)
        self.grids[key] = g
        if self.selected is None:
            self._select(key, monitor.n // 2)

    def _select(self, key, index: int) -> None:
        self.selected = (key, index)
        m = self.monitors[key]
        _channel, board_id = key
        self.title.setText(f"board {board_id} · sensor {m.sensor_ids[index]} (fresh samples)")

    def _tare(self) -> None:
        for m in self.monitors.values():
            m.set_tare(TARE_S)
        self.statusBar().showMessage(f"tare: mean of the last {TARE_S:.0f} s of fresh readings", 3000)

    def _refresh_plot(self) -> None:
        if not self.selected:
            return
        key, s = self.selected
        m = self.monitors[key]
        t, f, fresh = m.window(self.window_s)
        keep = fresh[:, s]
        x = t[keep] - m.now
        y = f[keep, s, :].astype(float)
        if self.minus_tare.isChecked() and m.tare is not None:
            y = y - m.tare[s]
        for k, c in enumerate(self.curves):
            c.setData(x, y[:, k])

    def _refresh_status(self) -> None:
        st, ds = self.source.status, self.source.stats()
        parts = [
            st.description,
            "connected" if st.connected else f"not connected ({st.error})" if st.error else "…",
            f"{st.bytes} B",
            f"framing {ds.framing}",
        ]
        for key, m in self.monitors.items():
            parts.append(f"board {key[1]} ch {key[0]}: {m.scan_rate():.1f} scans/s, fresh {m.fresh_rate():.1f} Hz")
        parts.append(f"checksum errors {ds.checksum_errors}, malformed {ds.malformed}, skipped {ds.skipped_bytes} B")
        if (
            st.bytes
            and (self._last_scan_wall is None or time.monotonic() - self._last_scan_wall > 1.0)
            and not st.finished
        ):
            parts.append("⚠ bytes but no frames: check wiring, ground and power")
        if st.finished:
            parts.append("finished")
        self.status.setText("  │  ".join(parts))


def run(
    port: str | None,
    file: str | None,
    speed: float,
    loop: bool,
    record: str | None,
    saturation: int,
    screenshot: str | None,
    screenshot_after: float,
) -> int:
    app = pg.mkQApp("magarray")
    source = ReplaySource(file, speed=speed, loop=loop) if file else SerialSource(port, record=record)
    source.start()
    win = Viewer(source, saturation=saturation)
    win.resize(1300, 640)
    win.show()
    if screenshot:

        def shoot() -> None:
            win.grab().save(screenshot)
            app.quit()

        QtCore.QTimer.singleShot(int(screenshot_after * 1000), shoot)
    code = app.exec()
    source.stop()
    source.join(timeout=1.0)
    return code
