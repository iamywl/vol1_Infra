#!/usr/bin/env python3
"""
vol1_Infra Enterprise Architecture Diagram Generator via FigCraft MCP.

Generates 15 high-readability enterprise diagrams (Topology + Flow pairs for 00~06 + Overview)
following the 4-Persona Enterprise Design System:
  - Minimum font size >= 10.5pt across all cards, headers, badges, and arrow pills
  - Clean white cards (#FFFFFF) on #F8FAFC canvas with 4px left semantic accent stripes
  - 4 semantic colors only: Slate (#1E293B), Royal Blue (#1D4ED8), Deep Teal (#0F766E),
    Crimson (#B91C1C), and GCP Cloud Cerulean (#0369A1)
  - 100% official open-source icons (full-color CNCF / official project logos)

Usage:
  python3 proposal/scripts/build_diagrams_via_figcraft_mcp.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
FIGCRAFT_CLI = ROOT_DIR / ".tools" / "bin" / "figcraft-cli"
ICONS_DIR = ROOT_DIR / "proposal" / "assets" / "icons"
DIAGRAMS_DIR = ROOT_DIR / "proposal" / "assets" / "diagrams"

FONT_FAMILY = "Apple SD Gothic Neo"

# Semantic colors (Restrained Enterprise Palette)
NAVY = "#1E293B"
SLATE_SUB = "#475569"
SLATE_MUTED = "#64748B"
BORDER = "#CBD5E1"
BG_CANVAS = "#F8FAFC"

COL_INFRA = "#1E293B"   # Infrastructure / Control Plane / IaC
COL_APP = "#1D4ED8"     # Applications / Middleware / MSA / Service Mesh
COL_DATA = "#0F766E"    # Data Layer / Messaging / Observability Lake
COL_SEC = "#B91C1C"     # Security / Zero-Trust / Chaos / Blocking
COL_CLOUD = "#0369A1"   # Phase 2 Cloud (GCP / WireGuard / Bursting)

DARK_BADGE_ICONS = {"vault.svg"}


def estimate_text_px(txt: str, font_size: float) -> float:
    """Estimate rendered pixel width for mixed Korean + ASCII strings."""
    total = 0.0
    for ch in txt:
        total += font_size * (0.94 if ord(ch) > 127 else 0.56)
    return total


class FigCraftMCP:
    """Minimal JSON-RPC client for `.tools/bin/figcraft-cli mcp`."""

    def __init__(self, cli_path: Path, cwd: Path) -> None:
        self.proc = subprocess.Popen(
            [str(cli_path), "mcp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(cwd),
            text=True,
            bufsize=1,
        )
        self._id = 0
        self._icon_size_cache: dict[str, tuple[float, float]] = {}
        self._handshake()

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def _send(self, payload: dict[str, Any]) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()

    def _recv(self) -> dict[str, Any]:
        assert self.proc.stdout is not None
        while True:
            line = self.proc.stdout.readline()
            if not line:
                err = self.proc.stderr.read() if self.proc.stderr else ""
                raise RuntimeError(f"FigCraft MCP EOF. stderr={err}")
            line = line.strip()
            if line:
                return json.loads(line)

    def _handshake(self) -> None:
        self._send(
            {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "vol1-infra-enterprise", "version": "2.0"},
                },
            }
        )
        resp = self._recv()
        if "error" in resp:
            raise RuntimeError(f"MCP initialize failed: {resp['error']}")
        info = resp["result"]["serverInfo"]
        print(f"[FigCraft MCP] Connected: {info['name']} v{info['version']}")
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def tool(self, name: str, arguments: dict[str, Any]) -> Any:
        req_id = self._next_id()
        self._send(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )
        while True:
            msg = self._recv()
            if msg.get("id") == req_id:
                if "error" in msg:
                    raise RuntimeError(f"MCP tool {name} error: {msg['error']}")
                res = msg["result"]
                if res.get("isError"):
                    raise RuntimeError(f"MCP tool {name} returned isError: {res}")
                txt = res["content"][0]["text"]
                try:
                    return json.loads(txt)
                except json.JSONDecodeError:
                    return txt

    def run_cmd(self, command: str, params: dict[str, Any] | None = None) -> Any:
        return self.tool("run_command", {"command": command, "params": params or {}})

    def batch(self, commands: list[dict[str, Any]], label: str = "batch") -> Any:
        if not commands:
            return None
        return self.tool("batch", {"commands": commands, "label": label})

    def create_node(
        self,
        node_type: str,
        parent: int | None = None,
        x: float = 0,
        y: float = 0,
        width: float | None = None,
        height: float | None = None,
        name: str | None = None,
        text: str | None = None,
        props: dict[str, Any] | None = None,
    ) -> int:
        args: dict[str, Any] = {"type": node_type, "x": x, "y": y}
        if parent is not None:
            args["parent"] = parent
        if width is not None:
            args["width"] = width
        if height is not None:
            args["height"] = height
        if name is not None:
            args["name"] = name
        if text is not None:
            args["text"] = text
        if props:
            args["props"] = props
        return self.tool("create_node", args)["id"]

    def place_icon(
        self,
        icon_file: str,
        parent: int,
        x: float,
        y: float,
        box_size: float = 42.0,
        icon_pad: float = 4.0,
        badge_radius: float = 8.0,
    ) -> None:
        rel_path = f"proposal/assets/icons/{icon_file}"
        if not (ICONS_DIR / icon_file).exists():
            raise FileNotFoundError(f"Missing icon: {ICONS_DIR / icon_file}")

        bg = "#1E293B" if icon_file in DARK_BADGE_ICONS else "#FFFFFF"
        border = "#1E293B" if icon_file in DARK_BADGE_ICONS else "#E2E8F0"
        self.create_node(
            "rectangle",
            parent=parent,
            x=x,
            y=y,
            width=box_size,
            height=box_size,
            name=f"badge-{icon_file}",
            props={
                "fill": bg,
                "stroke": border,
                "strokeWeight": 1.0,
                "cornerRadius": badge_radius,
            },
        )
        target = box_size - icon_pad * 2
        if icon_file.endswith(".svg"):
            nid = self.run_cmd("file.import", {"path": rel_path, "x": 0, "y": 0})["id"]
            if icon_file not in self._icon_size_cache:
                info = self.tool("get_node", {"id": nid, "depth": 0, "fields": ["width", "height"]})
                self._icon_size_cache[icon_file] = (float(info["width"]), float(info["height"]))
            w, h = self._icon_size_cache[icon_file]
            factor = target / max(w, h, 1.0)
            self.run_cmd("transform.scale", {"ids": [nid], "factor": factor})
            self.run_cmd("node.reparent", {"ids": [nid], "parent": parent})
            nw, nh = w * factor, h * factor
            self.tool(
                "set_properties",
                {
                    "ids": [nid],
                    "props": {
                        "x": round(x + (box_size - nw) / 2.0, 2),
                        "y": round(y + (box_size - nh) / 2.0, 2),
                    },
                },
            )
        else:
            self.run_cmd(
                "image.place",
                {
                    "path": rel_path,
                    "parent": parent,
                    "x": round(x + icon_pad, 2),
                    "y": round(y + icon_pad, 2),
                    "width": target,
                    "height": target,
                    "mode": "fit",
                    "name": f"img-{icon_file}",
                },
            )

    def close(self) -> None:
        if self.proc.stdin:
            self.proc.stdin.close()
        self.proc.wait(timeout=10)


SOFT_SHADOW = [{"type": "dropShadow", "color": "#0F172A10", "offset": [0, 2], "radius": 8}]
CARD_SHADOW = [{"type": "dropShadow", "color": "#0F172A0A", "offset": [0, 1], "radius": 4}]


class EnterpriseDiagram:
    """High-readability enterprise diagram builder (min 10.5pt typography)."""

    def __init__(self, mcp: FigCraftMCP, frame_id: int, w: float = 1520, h: float = 920) -> None:
        self.mcp = mcp
        self.root = frame_id
        self.w = w
        self.h = h
        self._q: list[dict[str, Any]] = []

    def _add(self, command: str, params: dict[str, Any]) -> None:
        self._q.append({"command": command, "params": params})

    def flush(self) -> None:
        if self._q:
            for i in range(0, len(self._q), 80):
                self.mcp.batch(self._q[i : i + 80], label="enterprise-diagram")
            self._q.clear()

    def rect(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        fill: str | dict[str, Any],
        stroke: str | None = None,
        stroke_weight: float = 1.2,
        radius: float | list[float] = 8,
        dashes: list[float] | None = None,
        effects: list[dict[str, Any]] | None = None,
        name: str = "Rect",
    ) -> None:
        props: dict[str, Any] = {"cornerRadius": radius}
        if isinstance(fill, dict):
            props["fills"] = [fill]
        else:
            props["fill"] = fill
        if stroke:
            props["stroke"] = stroke
            props["strokeWeight"] = stroke_weight
        if dashes:
            props["dashes"] = dashes
        if effects:
            props["effects"] = effects
        self._add(
            "node.create",
            {
                "type": "rectangle",
                "parent": self.root,
                "x": x,
                "y": y,
                "width": w,
                "height": h,
                "name": name,
                "props": props,
            },
        )

    def text(
        self,
        x: float,
        y: float,
        txt: str,
        size: float = 11.5,
        color: str = NAVY,
        bold: bool = False,
        align: str = "left",
        width: float | None = None,
        name: str = "Text",
    ) -> None:
        assert size >= 10.5, f"Font size {size}pt violates >=10.5pt enterprise readability rule: {txt}"
        props: dict[str, Any] = {
            "fontFamily": FONT_FAMILY,
            "fontStyle": "Bold" if bold else "Regular",
            "fontSize": size,
            "fill": color,
            "textAlign": align,
        }
        if width is not None:
            props["textAutoResize"] = "height"
        params: dict[str, Any] = {
            "type": "text",
            "parent": self.root,
            "x": x,
            "y": y,
            "text": txt,
            "name": name,
            "props": props,
        }
        if width is not None:
            params["width"] = width
        self._add("node.create", params)

    def header(self, title: str, subtitle: str, chips: list[tuple[str, str]]) -> None:
        """Crisp enterprise header with >= 22pt title, 12.5pt subtitle, and dark semantic chips."""
        self.text(36, 18, title, size=22.0, color=NAVY, bold=True, width=1040)
        self.text(36, 50, subtitle, size=12.5, color=SLATE_SUB, width=1040)
        rx = self.w - 36
        for label, accent in reversed(chips):
            cw = max(108, estimate_text_px(label, 10.8) + 22)
            rx -= cw
            self.rect(rx, 24, cw, 28, fill="#FFFFFF", stroke=accent, stroke_weight=1.4, radius=6)
            self.rect(rx, 24, 5, 28, fill=accent, radius=[6, 0, 0, 6])
            self.text(rx + 8, 31, label, size=10.8, color=accent, bold=True, align="center", width=cw - 12)
            rx -= 10
        self.rect(36, 76, self.w - 72, 1.5, fill="#CBD5E1", radius=0, name="HeaderRule")

    def zone(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        title: str,
        spec: str,
        accent: str = COL_INFRA,
        badge: str | None = None,
        dashed: bool = False,
        icon: str | None = None,
        bg: str = "#FFFFFF",
    ) -> None:
        """Enterprise Zone container with subtle header band, crisp outline, and zero rainbow clutter."""
        self.rect(
            x,
            y,
            w,
            h,
            fill=bg,
            stroke=accent if dashed else "#CBD5E1",
            stroke_weight=1.6 if dashed else 1.4,
            radius=10,
            dashes=[7, 4] if dashed else None,
            effects=SOFT_SHADOW,
            name=f"zone-{title}",
        )
        # Clean top header strip (light tint + bottom hairline + bold dark title)
        hdr_h = 42
        hdr_bg = "#F1F5F9" if accent == COL_INFRA else (
            "#EFF6FF" if accent == COL_APP else (
                "#F0FDFA" if accent == COL_DATA else (
                    "#FEF2F2" if accent == COL_SEC else "#F0F9FF"
                )
            )
        )
        self.rect(x + 1, y + 1, w - 2, hdr_h, fill=hdr_bg, radius=[9, 9, 0, 0])
        self.rect(x + 1, y + 1, w - 2, 4, fill=accent, radius=[9, 9, 0, 0])
        self.rect(x + 1, y + hdr_h, w - 2, 1, fill="#E2E8F0", radius=0)
        self.flush()

        tx = x + 14
        if icon:
            self.mcp.place_icon(icon, self.root, x + 12, y + 8, box_size=28, icon_pad=3, badge_radius=6)
            tx = x + 48

        bw = 0.0
        if badge:
            bw = max(72, estimate_text_px(badge, 10.5) + 18)
            self.rect(x + w - bw - 12, y + 11, bw, 22, fill=accent, radius=5)
            self.text(x + w - bw - 10, y + 15, badge, size=10.5, color="#FFFFFF", bold=True, align="center", width=bw - 4)

        title_px = estimate_text_px(title, 14.0)
        avail = w - (tx - x) - (bw + 24 if badge else 14)
        self.text(tx, y + 13, title, size=13.8 if title_px <= avail else 12.8, color=NAVY, bold=True, width=avail)
        if spec:
            spec_x = tx + min(title_px, avail) + 14
            rem = x + w - (bw + 24 if badge else 14) - spec_x
            if rem > 100:
                self.text(spec_x, y + 15, spec, size=11.0, color=SLATE_MUTED, width=rem)

    def subpanel(self, x: float, y: float, w: float, h: float, title: str, spec: str = "", accent: str = COL_INFRA) -> None:
        self.rect(x, y, w, h, fill="#F8FAFC", stroke="#CBD5E1", stroke_weight=1.1, radius=8)
        self.text(x + 12, y + 8, title, size=11.8, color=NAVY, bold=True, width=w - 24)
        if spec:
            t_px = estimate_text_px(title, 11.8)
            if x + 12 + t_px + 14 < x + w - 90:
                self.text(x + 12 + t_px + 10, y + 9, spec, size=10.5, color=SLATE_MUTED, width=w - t_px - 32)

    def card(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        title: str,
        subtitle: str,
        icon: str,
        accent: str = COL_INFRA,
        badge: str | None = None,
        badge_bg: str | None = None,
        icon_size: float = 40.0,
    ) -> None:
        """
        Clean white enterprise node card:
          - 4px rounded accent bar on left
          - Official full-color icon on white tile
          - Crisp 13~14pt Bold title
          - Crisp >=10.8pt single-line (max 2 short lines) technical spec
          - High-contrast port/role badge top-right
        """
        self.rect(x, y, w, h, fill="#FFFFFF", stroke="#CBD5E1", stroke_weight=1.2, radius=8, effects=CARD_SHADOW, name=f"card-{title}")
        self.rect(x + 4, y + 8, 4, h - 16, fill=accent, radius=2)
        self.flush()

        ix = x + 15
        iy = y + (h - icon_size) / 2
        self.mcp.place_icon(icon, self.root, ix, iy, box_size=icon_size, icon_pad=4, badge_radius=7)

        tx = ix + icon_size + 11
        bw = 0.0
        if badge:
            bw = max(56, estimate_text_px(badge, 10.5) + 14)
            bbg = badge_bg or accent
            self.rect(x + w - bw - 10, y + 10, bw, 20, fill=bbg, radius=5)
            self.text(x + w - bw - 9, y + 13, badge, size=10.5, color="#FFFFFF", bold=True, align="center", width=bw - 2)

        t_avail = w - (tx - x) - (bw + 16 if badge else 12)
        t_size = 13.5 if estimate_text_px(title, 13.5) <= t_avail else 12.2
        if estimate_text_px(title, t_size) > t_avail:
            t_size = 11.4
        if estimate_text_px(title, t_size) > t_avail + 4:
            print(f"[WARN] Card title tight: '{title}' est={estimate_text_px(title, t_size):.1f} > avail={t_avail:.1f}", file=sys.stderr)
        self.text(tx, y + 11, title, size=t_size, color=NAVY, bold=True, width=t_avail)

        if subtitle:
            s_avail = w - (tx - x) - 10
            s_size = 11.0 if h >= 72 else 10.6
            self.text(tx, y + 35, subtitle, size=s_size, color=SLATE_SUB, width=s_avail)

    def compact_card(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        title: str,
        sub: str,
        icon: str,
        accent: str = COL_APP,
        badge: str | None = None,
    ) -> None:
        """Compact enterprise tile for 4-column MSA / common grids (strictly >= 10.5pt)."""
        self.rect(x, y, w, h, fill="#FFFFFF", stroke="#CBD5E1", stroke_weight=1.1, radius=7, effects=CARD_SHADOW)
        self.rect(x + 3, y + 7, 3.5, h - 14, fill=accent, radius=2)
        self.flush()
        self.mcp.place_icon(icon, self.root, x + 12, y + (h - 32) / 2, box_size=32, icon_pad=3, badge_radius=6)
        tx = x + 50
        bw = 0.0
        if badge:
            bw = max(46, estimate_text_px(badge, 10.5) + 10)
            self.rect(x + w - bw - 7, y + 8, bw, 18, fill=accent, radius=4)
            self.text(x + w - bw - 6, y + 10.5, badge, size=10.5, color="#FFFFFF", bold=True, align="center", width=bw - 2)
        t_avail = w - 50 - (bw + 12 if badge else 8)
        t_sz = 12.0 if estimate_text_px(title, 12.0) <= t_avail else 11.0
        self.text(tx, y + 9, title, size=t_sz, color=NAVY, bold=True, width=t_avail)
        if sub:
            self.text(tx, y + 30, sub, size=10.5, color=SLATE_SUB, width=w - 56)

    def step_badge(self, x: float, y: float, w: float, h: float, title: str, icon: str, accent: str = COL_INFRA) -> None:
        self.rect(x, y, w, h, fill="#F8FAFC", stroke="#CBD5E1", stroke_weight=1.0, radius=6)
        self.flush()
        self.mcp.place_icon(icon, self.root, x + 8, y + (h - 26) / 2, box_size=26, icon_pad=2, badge_radius=5)
        self.text(x + 40, y + (h - 14) / 2, title, size=10.8, color=NAVY, bold=True, width=w - 46)

    def _arrowhead(self, tip: tuple[float, float], prev: tuple[float, float], color: str, size: float = 9.0) -> None:
        import math
        dx, dy = tip[0] - prev[0], tip[1] - prev[1]
        dist = math.hypot(dx, dy)
        if dist < 1e-3:
            return
        ux, uy = dx / dist, dy / dist
        nx, ny = -uy, ux
        hw = size * 0.52
        bx, by = tip[0] - ux * size, tip[1] - uy * size
        p1 = (round(bx + nx * hw, 2), round(by + ny * hw, 2))
        p2 = (round(bx - nx * hw, 2), round(by - ny * hw, 2))
        pts = [tip, p1, p2]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        mx, my = min(xs), min(ys)
        poly = " ".join(f"{'M' if i == 0 else 'L'} {round(p[0] - mx, 2)} {round(p[1] - my, 2)}" for i, p in enumerate(pts)) + " Z"
        self._add(
            "node.create",
            {
                "type": "vector",
                "parent": self.root,
                "x": mx,
                "y": my,
                "path": poly,
                "name": "ArrowHead",
                "props": {"fill": color, "stroke": "none"},
            },
        )

    def arrow(
        self,
        points: list[tuple[float, float]],
        color: str = COL_INFRA,
        weight: float = 2.0,
        dashed: bool = False,
        bidir: bool = False,
        label: str | None = None,
        label_pos: tuple[float, float] | None = None,
    ) -> None:
        assert len(points) >= 2
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        min_x, min_y = min(xs), min(ys)
        d = " ".join(
            f"{'M' if i == 0 else 'L'} {round(px - min_x, 1)} {round(py - min_y, 1)}"
            for i, (px, py) in enumerate(points)
        )
        props: dict[str, Any] = {
            "stroke": color,
            "strokeWeight": weight,
            "strokeCap": "round",
            "strokeJoin": "round",
        }
        if dashed:
            props["dashes"] = [6, 4]
        self._add(
            "node.create",
            {
                "type": "vector",
                "parent": self.root,
                "x": min_x,
                "y": min_y,
                "path": d,
                "name": f"Arrow-{label or 'flow'}",
                "props": props,
            },
        )
        self._arrowhead(points[-1], points[-2], color)
        if bidir:
            self._arrowhead(points[0], points[1], color)
        if label:
            lx, ly = label_pos if label_pos else ((points[0][0] + points[-1][0]) / 2, (points[0][1] + points[-1][1]) / 2)
            lw = max(62, estimate_text_px(label, 10.5) + 16)
            self.rect(lx - lw / 2, ly - 11, lw, 22, fill="#FFFFFF", stroke=color, stroke_weight=1.2, radius=5)
            self.text(lx - lw / 2 + 2, ly - 6, label, size=10.5, color=color, bold=True, align="center", width=lw - 4)

    def foundation(self, y: float) -> None:
        """Consistent enterprise host & node baseline bar at bottom."""
        self.rect(36, y, self.w - 72, 42, fill="#FFFFFF", stroke="#CBD5E1", stroke_weight=1.2, radius=8, effects=CARD_SHADOW)
        self.text(50, y + 14, "ALL 10 NODES COMMON", size=11.0, color=SLATE_SUB, bold=True, width=165)
        commons = [
            ("containerd 1.7", "containerd.png", 142),
            ("kubeadm v1.31", "kubernetes.png", 142),
            ("Cilium eBPF", "cilium.png", 130),
            ("Hubble Relay", "hubble.png", 132),
            ("Tetragon eBPF", "tetragon.png", 140),
            ("Prom Exporters", "prometheus.png", 146),
            ("Tart ARM64 VM", "tart.png", 142),
            ("M4 Max 128G ($0)", "apple.svg", 160),
        ]
        cx = 222
        for cname, cicon, cw in commons:
            self.step_badge(cx, y + 6, cw, 30, cname, cicon)
            cx += cw + 8


_PAGE_COUNT = 0


def new_frame(mcp: FigCraftMCP, page_name: str, frame_name: str, w: float = 1520, h: float = 920) -> int:
    global _PAGE_COUNT
    if _PAGE_COUNT == 0:
        mcp.run_cmd("page.rename", {"name": page_name})
    else:
        pid = mcp.run_cmd("page.add", {})["id"]
        mcp.run_cmd("page.select", {"id": pid})
        mcp.run_cmd("page.rename", {"name": page_name})
    _PAGE_COUNT += 1
    return mcp.create_node(
        "frame",
        x=0,
        y=0,
        width=w,
        height=h,
        name=frame_name,
        props={"fill": BG_CANVAS},
    )


# ===========================================================================
# 00-A: Master Integration Topology
# ===========================================================================
def build_00_master(mcp: FigCraftMCP) -> int:
    fid = new_frame(mcp, "00-Master-Topology", "00-master-integration-architecture", 1520, 920)
    d = EnterpriseDiagram(mcp, fid, 1520, 920)
    d.header(
        "[00-A] vol1_Infra 통합 4-클러스터 아키텍처 토폴로지 (10 VM · Phase 1 → Phase 2 GCP)",
        "IaC_apple_sillicon · devsecops · Middleware_Hello · service_infra 통합 배치 및 LearingGCP 확장 경계",
        [("Phase 1: M4 Max ($0)", COL_INFRA), ("Phase 2: GCP Bridge", COL_CLOUD)],
    )

    # Top Left: Platform Cluster (x=36, y=92, w=728, h=376) -> opens 68px gutter to Dev(x=832)
    d.zone(36, 92, 728, 376, "Platform Cluster (10.10.0.0/16)", "3 VMs · 7 vCPU · 24 GB", COL_INFRA, "platform", icon="kubernetes.png")
    d.subpanel(50, 146, 344, 308, "platform-worker1 (3C / 12 GB)", "관제 레이크", COL_DATA)
    d.card(62, 178, 320, 62, "Scouter Server 2.20", "Tomcat XLog · JVM Heap 프로파일링", "scouter.png", COL_DATA, ":6100/:6180")
    d.card(62, 246, 320, 62, "Jaeger + Prometheus", "OTel 분산 트레이스 + TSDB(15s Scrape)", "jaeger.png", COL_DATA, ":4317/:9090")
    d.card(62, 314, 320, 62, "Loki vs Elasticsearch 8", "라벨(512Mi) vs Nori 역인덱싱 · SIEM", "elasticsearch.svg", COL_DATA, ":3100/:9200")
    d.card(62, 382, 320, 62, "Grafana + AlertManager", "4축 상관분석 UI + 8대 경보 룰", "grafana.png", COL_DATA, ":30300/:30903")

    d.subpanel(406, 146, 344, 308, "platform-worker2 (2C / 8 GB)", "CI/CD · Sec", COL_INFRA)
    d.card(418, 178, 320, 62, "Jenkins + Buildx CI", "Lint · Test · Multi-Arch(arm64/amd64)", "jenkins.svg", COL_INFRA, ":30900")
    d.card(418, 246, 320, 62, "ArgoCD v2.13 + Harbor", "GitOps Auto-Sync + OCI(:30400)", "argocd.png", COL_INFRA, ":30800/:30400")
    d.card(418, 314, 320, 62, "Vault + Sealed Secrets", "동적 DB 시크릿 + Git 정적 암호화", "vault.svg", COL_SEC, ":8200")
    d.card(418, 382, 320, 62, "Velero v1.10 + MinIO", "네임스페이스/PV 백업 + etcdctl DR", "velero.png", COL_DATA, ":9000")

    # Top Right: Dev + Staging (x=832, y=92, w=652, h=376)
    d.zone(832, 92, 320, 376, "Dev (10.20.0.0/16)", "2 VMs · 4C/12G", COL_APP, "dev", icon="istio.png")
    d.card(844, 150, 296, 68, "Istio Mesh & Canary", "STRICT mTLS · 80/20 · Breaker", "istio.png", COL_APP, ":15012")
    d.card(844, 226, 296, 68, "Keycloak 24.0 OIDC", "middleware-realm 통합 JWT 발급", "keycloak.png", COL_APP, ":30880")
    d.card(844, 302, 296, 68, "Cilium L7 + Trivy Op", "Default-Deny + CVE CRD 스캔", "trivy.png", COL_SEC, "L7 eBPF")
    d.card(844, 378, 296, 68, "HPA + PDB (Dev Apps)", "CPU 50% 오토스케일 사전 검증", "kubernetes.png", COL_APP, "metrics")

    d.zone(1168, 92, 316, 376, "Staging (10.30.0.0/16)", "2 VMs · 4C/12G", COL_INFRA, "staging", icon="k6.svg")
    d.card(1180, 150, 292, 68, "k6 Load Gen (500 VU)", "16종 부하 프리셋 P95/P99 검증", "k6.svg", COL_APP, "300 RPS")
    d.card(1180, 226, 292, 68, "10-Scenario Chaos", "노드 정지·OOM·Pool 고갈 훈련", "prometheus.png", COL_SEC, "MTTR<1m")
    d.card(1180, 302, 292, 68, "SRE Ops UI (React 19)", "6 Pages · 11 APIs 토폴로지 관제", "hubble.png", COL_INFRA, ":5173")
    d.card(1180, 378, 292, 68, "Pre-Prod Helm Gate", "Tuning 전/후 처리량 승격 심사", "helm.png", COL_INFRA, "Gate")

    # Bottom Left: Prod Cluster (x=36, y=504, w=914, h=348) -> opens 68px gutter to Phase 2(x=1018)
    d.zone(36, 504, 914, 348, "Prod Cluster (10.40.0.0/16 · 2-Worker Active-Active HA)", "3 VMs · 6 vCPU · 20 GB", COL_APP, "prod", icon="nginx.svg")
    d.subpanel(50, 556, 434, 210, "Track A: 3-Tier Legacy (Middleware_Hello)", "HA", COL_APP)
    d.card(60, 588, 202, 62, "Nginx 1.24", "SSL 종료 · Path 분기", "nginx.svg", COL_APP, ":80/:443")
    d.card(272, 588, 202, 62, "Tomcat 10", "Spring Boot 3 (#1/#2)", "tomcat.svg", COL_APP, ":8080")
    d.card(60, 660, 414, 94, "MySQL 8.0 + Strangler Event Bridge", "middleware_db(:3306 SSL) + RabbitMQ 이벤트 브릿지 발행", "mysql.svg", COL_DATA, ":3306")

    d.subpanel(498, 556, 438, 210, "Track B: Cloud-Native 8-MSA (service_infra)", "Saga", COL_DATA)
    d.card(508, 588, 204, 62, "Kong GW", "Rate Limit · JWT 검증", "kong.svg", COL_APP, ":8000")
    d.card(722, 588, 204, 62, "FastAPI MSA", "Order·Pay·Search·Noti", "fastapi.svg", COL_APP, "8x:8000")
    d.card(508, 660, 418, 94, "Polyglot Data Layer (StatefulSet)", "PG 16(:5432) · Redis 7(:6379) · RabbitMQ 4(:5672) · ES 8(:9200)", "postgresql.svg", COL_DATA, "Saga")

    # Bottom security bar inside Prod
    d.step_badge(50, 778, 282, 58, "OPA Gatekeeper (5종 차단)", "opa.png", COL_SEC)
    d.step_badge(346, 778, 282, 58, "Trivy Operator (CVE 감시)", "trivy.png", COL_SEC)
    d.step_badge(642, 778, 294, 58, "Cilium L7 + Tetragon SIGKILL", "tetragon.png", COL_SEC)

    # Bottom Right: Phase 2 GCP Bridge (x=1018, y=504, w=466, h=348)
    d.zone(1018, 504, 466, 348, "Phase 2: GCP Cloud (LearingGCP)", "월 $10 크레딧+실지출 $30~45", COL_CLOUD, "Phase 2", dashed=True, icon="gcp.svg")
    d.card(1034, 558, 434, 64, "WireGuard + Cilium ClusterMesh", "M4 Max(10.10) ↔ GCP(10.50) L3/mTLS 브릿지", "wireguard.svg", COL_CLOUD, ":51871/:2379")
    d.card(1034, 630, 434, 64, "GKE Zonal Spot (서울 + 아이오와 DR)", "Cloud Bursting(500 VU) · Multi-Region(RTO<5s)", "gcp.svg", COL_CLOUD, "CP $0")
    d.card(1034, 702, 434, 64, "GCE N2 Nested KVM (Firecracker)", "125ms 독립 Guest 커널(kata-fc) · AI 샌드박스", "firecracker.png", COL_CLOUD, "/dev/kvm")
    d.card(1034, 774, 434, 64, "Crossplane IDP + Kyverno + GCS", "Claim PR 클라우드 프로비저닝 · 오프사이트 DR", "crossplane.png", COL_CLOUD, "GitOps")

    # Clean gutter arrows in 68px/36px corridors
    d.arrow([(764, 280), (832, 280)], color=COL_INFRA, label="GitOps", label_pos=(798, 280))
    d.arrow([(400, 468), (400, 504)], color=COL_DATA, bidir=True, label="① Sync/Obs", label_pos=(400, 486))
    d.arrow([(950, 678), (1018, 678)], color=COL_CLOUD, dashed=True, bidir=True, label="② Mesh", label_pos=(984, 678))

    d.foundation(866)
    d.flush()
    return fid


# ===========================================================================
# 00-B: As-Is -> To-Be Consolidation Mapping
# ===========================================================================
def build_00b_consolidation(mcp: FigCraftMCP) -> int:
    fid = new_frame(mcp, "00b-Repo-Consolidation", "00b-as-is-to-be-consolidation", 1520, 680)
    d = EnterpriseDiagram(mcp, fid, 1520, 680)
    d.header(
        "[00-B] 기존 4개 레포지토리 + LearingGCP 중복 제거 및 단일화 구조 (As-Is → To-Be)",
        "레포별로 중복 존재하던 관제(3세트), 레지스트리(2종), 인증, 정책, IaC 스크립트를 하나의 정본으로 결합한다",
        [("중복 제거 기준", COL_SEC), ("표준 정본 확정", COL_DATA)],
    )

    d.zone(36, 94, 440, 560, "As-Is: 5개 입력 레포지토리", "분산 · 중복 자산", COL_INFRA, "As-Is", icon="github.svg")
    d.card(52, 152, 408, 86, "IaC_apple_sillicon", "10 VM · Prom/Grafana/Loki · Harbor(30400/30500)\nGatekeeper 4종 · k6 16종 · Bash 01~17단계", "tart.png", COL_INFRA, "Base")
    d.card(52, 250, 408, 86, "devsecops", "Terraform>=1.5 · Ansible(setup-cluster.yml)\nTrivy · Gatekeeper 3종 · Vault(:8200) · Harbor", "trivy.png", COL_SEC, "SecOps")
    d.card(52, 348, 408, 86, "Middleware_Hello", "Docker Compose · Nginx · Tomcat 10 · MySQL 8\nScouter 2.20 · Keycloak 24 · 자체 Prom/Grafana", "tomcat.svg", COL_APP, "3-Tier")
    d.card(52, 446, 408, 86, "service_infra", "Kong · FastAPI 8-MSA · PG/Redis/Rabbit/ES\nOTel/Jaeger · 자체 Helm Prom/Loki/Harbor", "fastapi.svg", COL_DATA, "8-MSA")
    d.card(52, 544, 408, 94, "LearingGCP (8대 클라우드 안건)", "GKE Spot · N2 Firecracker(kata-fc) · Tetragon\n서울/아이오와 DR · Hybrid LLM · Crossplane IDP", "gcp.svg", COL_CLOUD, "Phase 2")

    d.zone(536, 94, 448, 560, "통합 및 중복 제거 규칙 (Deduplication)", "충돌 해소 · 표준화", COL_SEC, "Merge Rules", icon="opa.png")
    d.card(552, 152, 416, 86, "1. 관제 스택 3중 중복 → 1곳 집중", "MW·service·IaC의 개별 Prom/Grafana 제거\n→ platform-worker1 단일 레이크로 통합", "grafana.png", COL_DATA, "Single Lake")
    d.card(552, 250, 416, 86, "2. IaC · 레지스트리 포트 표준화", "Bash(01~06) · TF(K8s) · Ansible(Sec) 분리\nHarbor sh(:30500) 불일치 → :30400 통일", "terraform.png", COL_INFRA, "SSOT")
    d.card(552, 348, 416, 86, "3. Ingress · SSO · DB 브릿지 연결", "/legacy/* vs /api/v1/* URL 경로 분리\nKeycloak 단일 JWKS + RabbitMQ 동기화", "keycloak.png", COL_APP, "Unified SSO")
    d.card(552, 446, 416, 86, "4. Gatekeeper + 시크릿 이중 역할", "4종+3종 → prod 5대 정책 제약으로 합병\n정적(SealedSecrets) vs 동적(Vault) 분리", "vault.svg", COL_SEC, "5-Layer Sec")
    d.card(552, 544, 416, 94, "5. ARM64 로컬 + x86_64 GCP 연결", "Buildx Multi-Arch로 동일 태그 공용 빌드\nWireGuard + ClusterMesh로 KVM/DR 확장", "wireguard.svg", COL_CLOUD, "Hybrid")

    d.zone(1044, 94, 440, 560, "To-Be: vol1_Infra 통합 아키텍처", "단일 4-클러스터 + GCP", COL_DATA, "To-Be", icon="kubernetes.png")
    d.card(1060, 152, 408, 70, "[01] 3-Tier HA + 8-MSA 하이브리드", "Nginx/Tomcat/MySQL ↔ Kong/FastAPI 공존", "kong.svg", COL_APP, "Doc 01")
    d.card(1060, 234, 408, 70, "[02] Scouter × Jaeger × Hubble + ES/Loki", "4축 관제 상관분석 & 로그 엔진 정량 비교", "scouter.png", COL_DATA, "Doc 02")
    d.card(1060, 316, 408, 70, "[03] 5계층 Zero-Trust + Tetragon SIEM", "Cosign·Gatekeeper·Vault·mTLS·SIGKILL", "tetragon.png", COL_SEC, "Doc 03")
    d.card(1060, 398, 408, 70, "[04] 4단계 IaC + GitOps & Crossplane IDP", "Tart→TF→Ansible→ArgoCD ApplicationSet", "argocd.png", COL_INFRA, "Doc 04")
    d.card(1060, 480, 408, 70, "[05] k6 500 VU · Istio · Saga · 멀티리전 DR", "10대 카오스 + Velero RTO<5m / DR<5s", "velero.png", COL_DATA, "Doc 05")
    d.card(1060, 562, 408, 76, "[06] runc vs Firecracker MicroVM & AI 브릿지", "containerd 분기 + N2 /dev/kvm + 7안 LLM", "firecracker.png", COL_CLOUD, "Doc 06")

    for ay in [195, 293, 391, 489, 591]:
        d.arrow([(476, ay), (536, ay)], color=COL_INFRA)
    for ay in [188, 270, 352, 434, 516, 596]:
        d.arrow([(984, ay), (1044, ay)], color=COL_DATA)

    d.flush()
    return fid


# ===========================================================================
# 01-A: Hybrid Middleware + 8-MSA Topology
# ===========================================================================
def build_01_proposal1(mcp: FigCraftMCP) -> int:
    fid = new_frame(mcp, "01-Middleware-MSA", "01-proposal1-hybrid-middleware-msa", 1520, 920)
    d = EnterpriseDiagram(mcp, fid, 1520, 920)
    d.header(
        "[01-A] Track A(레거시 3-Tier WEB/WAS/DB) + Track B(8-MSA) 단일 K8s 통합 토폴로지",
        "Middleware_Hello와 service_infra를 prod 클러스터로 통합하고 Keycloak OIDC와 Cilium L7 정책을 공유한다",
        [("Track A: 3-Tier HA", COL_APP), ("Track B: 8-MSA Saga", COL_DATA)],
    )

    # Left Column: Shared Edge & Security (x=36, y=92, w=324, h=760) -> opens 64px gutter to Track A/B(x=424)
    d.zone(36, 92, 324, 760, "공통 엣지 · SSO · 보안", "단일 진입", COL_INFRA, "Gateway", icon="metallb.png")
    d.card(50, 152, 296, 72, "k6 / Client Traffic", "브라우저 · API · 부하 트래픽", "k6.svg", COL_INFRA, ":443")
    d.card(50, 240, 296, 78, "MetalLB + NGINX Ingress", "TLS 종료 · /legacy vs /api", "nginx.svg", COL_APP, ":443")
    d.card(50, 336, 296, 78, "Keycloak 24.0 OIDC", "middleware-realm JWT 발급", "keycloak.png", COL_APP, ":30880")
    d.card(50, 432, 296, 78, "Kong Gateway", "Rate Limit · CORS · JWT 검증", "kong.svg", COL_DATA, ":8000")
    d.card(50, 528, 296, 78, "Istio Envoy Mesh", "STRICT mTLS · 3회 5xx 격리", "istio.png", COL_APP, ":15012")
    d.card(50, 624, 296, 78, "Cilium L7 Policy", "Default-Deny · HTTP 필터", "cilium.png", COL_SEC, "eBPF L7")
    d.card(50, 720, 296, 114, "핵심 통합 원칙", "1회 로그인으로 양 트랙 인증\nURL 접두사로 무중단 분기", "kubernetes.png", COL_INFRA, "Unified")

    # Right Top: Track A 3-Tier Legacy WAS (x=424, y=92, w=1060, h=238)
    d.zone(424, 92, 1060, 238, "Track A: 레거시 3-Tier 미들웨어 (Middleware_Hello → prod/legacy-was)", "StatefulSet + Anti-Affinity HA", COL_APP, "Track A", icon="tomcat.svg")
    d.card(440, 146, 240, 74, "Nginx 1.24 Web Tier", "Round Robin · /stub_status", "nginx.svg", COL_APP, ":80")
    d.card(704, 146, 250, 74, "Apache Tomcat 10 HA", "Spring Boot 3 (#1 / #2)", "tomcat.svg", COL_APP, ":8080")
    d.card(978, 146, 240, 74, "MySQL 8.0", "middleware_db · PVC · SSL", "mysql.svg", COL_DATA, ":3306")
    d.card(1240, 146, 228, 74, "Scouter 2.20", "-javaagent XLog 수집", "scouter.png", COL_DATA, ":6100")
    d.card(440, 250, 1028, 66, "Strangler Fig 도메인 이벤트 브릿지 (Spring AMQP → RabbitMQ :5672)", "레거시 Tomcat에서 상품/회원 변경 시 MySQL 커밋 후 RabbitMQ로 이벤트 발행 → FastAPI search(ES Nori)·notification 즉시 동기화", "spring.svg", COL_DATA, "AMQP Bridge")

    # Right Bottom: Track B Cloud-Native 8-MSA (x=424, y=358, w=1060, h=494)
    d.zone(424, 358, 1060, 494, "Track B: 클라우드 네이티브 8-MSA (service_infra → prod/ecommerce)", "Python 3.12 · FastAPI 0.115.6 · OTel 1.29", COL_DATA, "Track B", icon="fastapi.svg")
    d.subpanel(440, 410, 1028, 196, "8-Microservices Fleet (K8s Service Internal :8000 · Local Port-Forward :8001~:8008)", "SQLAlchemy 2.0 + aio-pika 9.5", COL_APP)
    msas = [
        ("user-service", "회원 · JWT · 배송지", ":8001"),
        ("product-service", "상품 · 비관락 재고", ":8002"),
        ("order-service", "주문 · Saga 오케스트", ":8003"),
        ("payment-service", "멱등 결제 · 환불", ":8004"),
        ("delivery-service", "배송 추적 · 웹훅", ":8005"),
        ("search-service", "ES Nori 한국어 검색", ":8006"),
        ("review-service", "구매인증 리뷰 · 평점", ":8007"),
        ("notification-svc", "DLQ · 다채널 알림", ":8008"),
    ]
    for i, (mn, ms, mp) in enumerate(msas):
        col, row = i % 4, i // 4
        d.compact_card(454 + col * 250, 444 + row * 74, 238, 62, mn, ms, "fastapi.svg", COL_APP, mp)

    d.subpanel(440, 620, 1028, 214, "Polyglot Data & Messaging Layer (Kubernetes StatefulSet / Helm)", "서비스별 DB 격리 · 캐시 · 이벤트 · 검색", COL_DATA)
    d.card(454, 654, 490, 76, "PostgreSQL 16.6 (서비스별 독립 DB)", "user_db, product_db, order_db, payment_db, delivery_db, review_db", "postgresql.svg", COL_DATA, ":5432")
    d.card(960, 654, 490, 76, "Redis 7.4.2 (세션 · 장바구니 · 캐시)", "장바구니 상태 · 인기 검색어 · Keycloak 토큰 블랙리스트", "redis.svg", COL_SEC, ":6379")
    d.card(454, 744, 490, 76, "RabbitMQ 4.0.5 (Saga + Strangler 버스)", "order.created→payment→product 실패 시 보상 이벤트 & DLQ", "rabbitmq.svg", COL_INFRA, ":5672")
    d.card(960, 744, 490, 76, "Elasticsearch 8.17 + Nori 형태소 분석", "한국어 상품 색인 · 자동완성 · Strangler Fig 실시간 색인", "elasticsearch.svg", COL_DATA, ":9200")

    # Arrows strictly inside gutters & clear horizontal corridors (no crossing Strangler Fig!)
    d.arrow([(198, 224), (198, 240)], color=COL_INFRA)
    d.arrow([(346, 279), (392, 279), (392, 183), (440, 183)], color=COL_APP, label="① /legacy/*", label_pos=(392, 152))
    d.arrow([(346, 471), (440, 471)], color=COL_DATA, label="② /api/v1/*", label_pos=(392, 471))
    d.arrow([(346, 375), (402, 375), (402, 235), (829, 235), (829, 220)], color=COL_INFRA, dashed=True, label="③ JWKS", label_pos=(590, 235))
    d.arrow([(680, 183), (704, 183)], color=COL_APP)
    d.arrow([(954, 183), (978, 183)], color=COL_DATA)
    d.arrow([(1468, 283), (1498, 283), (1498, 842), (699, 842), (699, 820)], color=COL_DATA, bidir=True, label="④ AMQP :5672", label_pos=(1430, 344))

    d.foundation(866)
    d.flush()
    return fid


# ===========================================================================
# 01-B: Ingress Split, Unified OIDC & Strangler Fig Request Flow
# ===========================================================================
def build_01b_flow(mcp: FigCraftMCP) -> int:
    fid = new_frame(mcp, "01b-Request-SSO-Flow", "01b-proposal1-request-sso-strangler-flow", 1520, 680)
    d = EnterpriseDiagram(mcp, fid, 1520, 680)
    d.header(
        "[01-B] 경로 분기(/legacy vs /api) · Keycloak OIDC 단일 인증 · Strangler Fig 동기화 흐름",
        "1회 로그인으로 발급된 Bearer JWT를 두 트랙이 공통 검증하며, 레거시 변경은 RabbitMQ로 비동기 이관한다",
        [("Track A ↔ Track B 연결", COL_DATA), ("Zero-Trust mTLS", COL_SEC)],
    )

    # Lane 1 (y=92, h=144): OIDC Unified Authentication
    d.zone(36, 92, 1448, 144, "Flow ①: Keycloak 24.0 단일 OIDC 인증 & JWKS 공동 검증", "1회 인증으로 Track A/B 통합 접근", COL_INFRA, "Auth")
    d.card(56, 148, 300, 74, "1. Client Login", "브라우저 / API / k6 OAuth2 요청", "k6.svg", COL_INFRA, "HTTPS")
    d.card(426, 148, 340, 74, "2. Keycloak 24.0 (:30880)", "middleware-realm JWT 서명 발급", "keycloak.png", COL_APP, "OIDC")
    d.card(836, 148, 300, 74, "3A. Tomcat Spring Security", "JWKS 공개키 캐시로 토큰 검증", "tomcat.svg", COL_APP, "Track A")
    d.card(1186, 148, 280, 74, "3B. Kong + FastAPI Auth", "동일 JWKS로 8-MSA 토큰 인가", "kong.svg", COL_DATA, "Track B")
    d.arrow([(356, 185), (426, 185)], color=COL_INFRA, label="Auth")
    d.arrow([(766, 185), (836, 185)], color=COL_APP, label="JWT")
    d.arrow([(1136, 185), (1186, 185)], color=COL_DATA, dashed=True, label="JWKS")

    # Lane 2 (y=256, h=222): URL Path Prefix Routing (Track A vs Track B)
    d.zone(36, 256, 1448, 222, "Flow ②: NGINX Ingress 경로 기반 이중 트랙 라우팅 및 데이터 계층 분리", "L7 Prefix Routing", COL_APP, "Traffic")
    d.card(56, 336, 280, 96, "NGINX Ingress (:443)", "TLS 1.3 종료 · L7 Path 분기\n/legacy/* vs /api/v1/*", "nginx.svg", COL_INFRA, ":443")
    d.card(410, 312, 240, 68, "Nginx 1.24 Front", "Round Robin + /stub_status", "nginx.svg", COL_APP, ":80")
    d.card(700, 312, 280, 68, "Tomcat 10 HA (#1/#2)", "WAS 이중화 · Scouter Agent", "tomcat.svg", COL_APP, ":8080")
    d.card(1050, 312, 416, 68, "MySQL 8.0 (middleware_db)", "JDBC SSL 커넥션 풀 · PVC 영속 저장", "mysql.svg", COL_DATA, ":3306")

    d.card(410, 396, 240, 68, "Kong GW (:8000)", "Rate Limit · CORS", "kong.svg", COL_DATA, ":8000")
    d.card(700, 396, 280, 68, "FastAPI 8-MSA (Istio mTLS)", "ORDER / PAY / PRODUCT / USER", "fastapi.svg", COL_APP, ":8000")
    d.card(1050, 396, 416, 68, "PostgreSQL 16 + Redis 7", "서비스별 독립 DB + 장바구니·세션 캐시", "postgresql.svg", COL_DATA, ":5432/:6379")

    d.arrow([(336, 360), (410, 346)], color=COL_APP, label="/legacy/*")
    d.arrow([(650, 346), (700, 346)], color=COL_APP)
    d.arrow([(980, 346), (1050, 346)], color=COL_DATA, label="JDBC")
    d.arrow([(336, 405), (410, 430)], color=COL_DATA, label="/api/v1/*")
    d.arrow([(650, 430), (700, 430)], color=COL_APP)
    d.arrow([(980, 430), (1050, 430)], color=COL_DATA, label="Async SQL")

    # Lane 3 (y=498, h=154): Strangler Fig Event Bridge
    d.zone(36, 498, 1448, 154, "Flow ③: Strangler Fig 무중단 데이터 동기화 (이중 쓰기 제거)", "도메인 이벤트 기반 비동기 동기화", COL_DATA, "Strangler Fig")
    d.card(56, 558, 320, 76, "Tomcat (Spring AMQP)", "회원·상품 변경 커밋 후 이벤트 발행", "spring.svg", COL_APP, "Producer")
    d.card(446, 558, 320, 76, "RabbitMQ 4.0.5 (:5672)", "product.updated / order.legacy Queue", "rabbitmq.svg", COL_INFRA, "Broker")
    d.card(836, 558, 300, 76, "search / notification MSA", "aio-pika 컨슈머 · DLQ 실패 재처리", "fastapi.svg", COL_DATA, "Consumer")
    d.card(1196, 558, 270, 76, "Elasticsearch 8.17 Nori", "한국어 형태소 색인 실시간 갱신", "elasticsearch.svg", COL_DATA, ":9200")

    d.arrow([(376, 596), (446, 596)], color=COL_APP, label="Publish")
    d.arrow([(766, 596), (836, 596)], color=COL_DATA, label="Consume")
    d.arrow([(1136, 596), (1196, 596)], color=COL_DATA, label="Index")

    d.flush()
    return fid


# ===========================================================================
# 02-A: Observability Lake & GCP Offload Topology
# ===========================================================================
def build_02_proposal2(mcp: FigCraftMCP) -> int:
    fid = new_frame(mcp, "02-Observability-Lake", "02-proposal2-360-apm-observability", 1520, 920)
    d = EnterpriseDiagram(mcp, fid, 1520, 920)
    d.header(
        "[02-A] Scouter(XLog) × OpenTelemetry(Jaeger) × Hubble(eBPF) 통합 관제 토폴로지",
        "워커 노드에는 경량 수집기만 배치하고 무거운 TSDB·APM·듀얼 로그 저장소는 platform-worker1에 집중한다",
        [("4축 통합 관제", COL_DATA), ("Loki vs ES8 비교", COL_INFRA)],
    )

    d.zone(36, 92, 444, 756, "1. 관측 에이전트 (dev · staging · prod)", "저장 없이 원시 데이터 송출", COL_APP, "Producers", icon="opentelemetry.png")
    d.card(52, 154, 412, 92, "Scouter Java Agent 2.20", "Tomcat #1/#2 -javaagent XLog/SQL/Heap 수집", "tomcat.svg", COL_APP, "Agent")
    d.card(52, 266, 412, 92, "OpenTelemetry Python 1.29", "FastAPI httpx · aio-pika W3C traceparent 전파", "opentelemetry.png", COL_APP, "OTel SDK")
    d.card(52, 378, 412, 92, "Infra & App Exporters", "Node(:9100) · Nginx(:9113) · PG(:9187) · Redis(:9121)", "prometheus.png", COL_INFRA, "Pull")
    d.card(52, 490, 412, 92, "Promtail + Fluent-Bit", "Pod stdout JSON (trace_id) 듀얼 스트리밍", "fluentbit.png", COL_DATA, "Log Ship")
    d.card(52, 602, 412, 92, "Cilium Hubble + Tetragon", "eBPF 소켓 플로우 · L7 Drop · 커널 감사 로그", "cilium.png", COL_SEC, "eBPF Hook")
    d.card(52, 714, 412, 114, "에이전트 경량화 원칙 (FinOps)", "인덱싱·TSDB 저장을 워크로드 노드에 두지 않고\n로컬(platform)로 집계해 추후 GCP RAM 점유 < 800MB", "kubernetes.png", COL_INFRA, "<800MB")

    d.zone(540, 92, 476, 756, "2. 통합 데이터레이크 (platform-worker1)", "3 vCPU · 12 GB RAM 집중 적재", COL_DATA, "Data Lake", icon="prometheus.png")
    d.card(556, 154, 444, 110, "Scouter Collector Server 2.20", "UDP/TCP :6100 수신 · :6180 API\nXLog 분포 · SQL 지연 · Heap/Thread 분석", "scouter.png", COL_DATA, ":6100/:6180")
    d.card(556, 282, 444, 110, "Jaeger Distributed Tracing", "OTLP gRPC(:4317) 수신 · :16686 UI\n8-MSA 분산 트랜잭션 의존성 맵 생성", "jaeger.png", COL_APP, ":4317")
    d.card(556, 410, 444, 110, "Prometheus TSDB + AlertManager", "15s Scrape + Remote Write 수신(15일 보관)\n8대 PrometheusRule 경보 라우팅(:30903)", "prometheus.png", COL_SEC, ":9090/:30903")
    d.card(556, 538, 444, 128, "듀얼 로그 엔진: Loki vs ES 8.17", "① Loki(:3100): 라벨만 인덱싱 (512Mi 제한)\n② Elasticsearch 8(:9200): 전문 역인덱싱 + SIEM\n동일 k6 부하 시 RAM·검색 지연 정량 비교", "loki.png", COL_DATA, ":3100/:9200")
    d.card(556, 684, 444, 144, "Hubble Relay + Tetragon SIEM Sink", "4개 클러스터(10.10~10.40) eBPF 플로우 집계\n네트워크 차단(DROP) vs 앱 오류 즉시 분리\nTetragon 커널 감사 로그 → ES 8 SIEM 인덱싱", "hubble.png", COL_SEC, ":31235")

    d.zone(1076, 92, 408, 756, "3. 상관분석 UI & GCP 오프로딩", "MTTD/MTTR 단축", COL_INFRA, "UI + GCP", icon="grafana.png")
    d.card(1092, 154, 376, 114, "Grafana 4축 통합 대시보드", "Prom Exemplars → Jaeger TraceID 점프\nJaeger → Loki/ES8 Derived Fields 연계", "grafana.png", COL_INFRA, ":30300")
    d.card(1092, 286, 376, 114, "SRE Operations Dashboard", "React 19 + Express 5 (6 Pages · 11 APIs)\nHubble SVG 토폴로지 & k6 16종 테스트", "kubernetes.png", COL_APP, ":5173")

    d.subpanel(1092, 422, 376, 406, "Phase 2: GCP Edge → M4 Max 오프로딩", "LearingGCP 2안 (-$120/월)", COL_CLOUD)
    d.card(1106, 462, 348, 96, "GCP GKE Spot: 경량 Agent만", "Prom Agent(WAL) · Fluent-Bit · Scouter\n무거운 DB/백엔드 배제 (<800MB RAM)", "gcp.svg", COL_CLOUD, "Edge Only")
    d.card(1106, 576, 348, 108, "WireGuard 역방향 텔레메트리", "GCP → M4 Max(128GB RAM) 암호화 전송\n서울(8ms) vs 아이오와(140ms) XLog 비교", "wireguard.svg", COL_CLOUD, ":51871")
    d.card(1106, 702, 348, 110, "상관분석 핵심 성과", "장애 원인 판별(MTTD) 1분 이내 단축\n동일 트래픽 내 Loki vs ES8 자원비 실측", "k6.svg", COL_DATA, "FinOps")

    d.arrow([(480, 200), (540, 200)], color=COL_APP, label="① :6100")
    d.arrow([(480, 312), (540, 312)], color=COL_APP, label="② :4317")
    d.arrow([(480, 424), (540, 465)], color=COL_INFRA, label="③ Scrape")
    d.arrow([(480, 536), (540, 596)], color=COL_DATA, label="④ Dual")
    d.arrow([(480, 648), (540, 740)], color=COL_SEC, label="⑤ eBPF")
    d.arrow([(1016, 212), (1076, 212)], color=COL_INFRA, label="⑥ Link")
    d.arrow([(1076, 626), (1016, 626)], color=COL_CLOUD, dashed=True, label="⑦ Offload")

    d.foundation(866)
    d.flush()
    return fid


# ===========================================================================
# 02-B: MTTR Correlation Pipeline & Dual Log Benchmark Flow
# ===========================================================================
def build_02b_correlation(mcp: FigCraftMCP) -> int:
    fid = new_frame(mcp, "02b-MTTR-Correlation", "02b-proposal2-mttr-correlation-pipeline", 1520, 680)
    d = EnterpriseDiagram(mcp, fid, 1520, 680)
    d.header(
        "[02-B] 4축 상관분석 기반 장애 추적(MTTR 단축) 및 Loki vs Elasticsearch 8 정량 비교",
        "AlertManager 경보 수신 → Hubble 네트워크 판별 → Jaeger/Scouter 병목 특정 → 로그 엔진 비교 파이프라인",
        [("5단계 장애 추적", COL_DATA), ("Dual Log 벤치마크", COL_INFRA)],
    )

    d.zone(36, 94, 1448, 250, "Part 1: 상관분석 장애 추적 표준 플로우 (MTTR Shortening)", "Metric → eBPF → Trace → XLog → Log", COL_INFRA, "Correlation")
    steps = [
        ("1. AlertManager 경보", "Nginx 5xx 급증 / P99 초과\n8대 PrometheusRule 발동", "prometheus.png", COL_SEC, ":30903"),
        ("2. Hubble 플로우 분리", "DROPPED 패킷 유무 확인\n네트워크 차단 vs 앱 오류", "hubble.png", COL_SEC, ":31235"),
        ("3. Exemplar → Jaeger", "Grafana 점 → TraceID 점프\nTrack A vs B 지연 서비스 식별", "jaeger.png", COL_APP, ":16686"),
        ("4. Scouter XLog 정밀", "Tomcat 구간 SQL 바인딩\nJVM Heap / GC Pause 분석", "scouter.png", COL_APP, ":6180"),
        ("5. Loki/ES8 trace_id", "MSA trace_id JSON 필터\n예외 스택트레이스 즉시 확인", "grafana.png", COL_DATA, ":30300"),
    ]
    sx = 54
    for i, (st, ss, si, sa, sb) in enumerate(steps):
        d.card(sx, 154, 260, 166, st, ss, si, sa, sb)
        if i < len(steps) - 1:
            d.arrow([(sx + 260, 236), (sx + 288, 236)], color=sa)
        sx += 288

    d.zone(36, 366, 1448, 286, "Part 2: 동일 부하(k6 500 VU) 기반 듀얼 로그 엔진 비교 아키텍처", "Promtail Dual-Push Benchmark", COL_DATA, "Benchmark")
    d.card(56, 444, 280, 150, "k6 Load + App Stdout", "500 VU 부하 시 동일 JSON 로그\n(trace_id, service, level) 생성", "k6.svg", COL_APP, "500 VU")
    d.card(396, 444, 280, 150, "Promtail / Fluent-Bit", "동일 스트림을 Loki(:3100)와\nES 8(:9200)로 동시에 Dual Push", "fluentbit.png", COL_INFRA, "Dual Push")
    d.card(746, 420, 350, 98, "Grafana Loki (:3100)", "라벨만 인덱싱 · 512Mi 상한\n낮은 RAM/디스크 · 단건 trace_id 조회", "loki.png", COL_DATA, "Low RAM")
    d.card(746, 532, 350, 98, "Elasticsearch 8.17 (:9200)", "본문 전체 + Nori 역인덱싱 (Heap 1~2G+)\n복합 키워드 집계 · Tetragon SIEM 전담", "elasticsearch.svg", COL_SEC, "SIEM/FTS")
    d.card(1166, 444, 298, 150, "Grafana 비교 대시보드", "100만 건 기준 RSS 메모리 점유율,\n색인 지연(Lag), 쿼리 응답속도 비교", "grafana.png", COL_INFRA, "Metrics")

    d.arrow([(336, 519), (396, 519)], color=COL_APP)
    d.arrow([(676, 495), (746, 469)], color=COL_DATA)
    d.arrow([(676, 540), (746, 581)], color=COL_SEC)
    d.arrow([(1096, 469), (1166, 495)], color=COL_DATA)
    d.arrow([(1096, 581), (1166, 540)], color=COL_SEC)

    d.flush()
    return fid


# ===========================================================================
# 03-A: 5-Layer Zero-Trust DevSecOps Topology
# ===========================================================================
def build_03_proposal3(mcp: FigCraftMCP) -> int:
    fid = new_frame(mcp, "03-DevSecOps-Tetragon", "03-proposal3-zero-trust-devsecops", 1520, 920)
    d = EnterpriseDiagram(mcp, fid, 1520, 920)
    d.header(
        "[03-A] 5계층 Zero-Trust DevSecOps — 공급망 서명 × OPA 정책 × Cilium Tetragon eBPF SIEM",
        "devsecops · IaC_apple_sillicon · Middleware_Hello · LearingGCP 6안을 전 계층 심층 방어선으로 결합한다",
        [("5-Layer Defense", COL_SEC), ("Kernel SIGKILL SIEM", COL_INFRA)],
    )

    # Layer 1: Supply Chain (y=92, h=136)
    d.zone(36, 92, 1448, 136, "Layer 1: 소프트웨어 공급망 보안 (CI/CD Pipeline · Host + platform-worker2)", "빌드·취약점 검사·서명·레지스트리 적재", COL_INFRA, "devsecops + IaC", icon="github.svg")
    d.card(52, 144, 336, 72, "GitHub + Jenkins CI", "Lint · Unit Test · Non-Root 빌드", "jenkins.svg", COL_APP, ":30900")
    d.card(408, 144, 336, 72, "Trivy CLI Scan", "CRITICAL/HIGH CVE 파이프라인 차단", "trivy.png", COL_SEC, "CVE Gate")
    d.card(764, 144, 336, 72, "Buildx + Cosign 서명", "arm64+amd64 · 키리스 서명(.sig)", "docker.svg", COL_APP, "Cosign")
    d.card(1120, 144, 348, 72, "Harbor + Docker Hub", "프라이빗 스캔 · 공용 이미지 적재", "harbor.png", COL_INFRA, ":30400")

    # Layer 2 & Layer 3 side by side (y=264, h=192)
    d.zone(36, 264, 712, 192, "Layer 2: 클러스터 진입 통제 (Admission Control)", "prod 무결성 검증", COL_SEC, "Admission", icon="opa.png")
    d.card(50, 316, 218, 126, "ArgoCD v2.13", "서명 통과 매니페스트\nGitOps 자동 동기화", "argocd.png", COL_INFRA, ":30800")
    d.card(282, 316, 224, 126, "OPA Gatekeeper", ":latest 금지 · 특권 차단\nLimits · 필수 라벨 5종", "opa.png", COL_SEC, "5-Rules")
    d.card(520, 316, 214, 126, "Trivy Operator", "실행 중 파드 상시 스캔\nVulnerabilityReport", "trivy.png", COL_SEC, "CRD")

    d.zone(772, 264, 712, 192, "Layer 3: 아이덴티티 · 시크릿 · 접근통제 (IAM & Secrets)", "정적·동적 이원화", COL_APP, "IAM/Secrets", icon="vault.svg")
    d.card(786, 316, 218, 126, "Vault", "DB 동적 자격증명 · PKI\nAgent Injector 주입", "vault.svg", COL_SEC, ":8200")
    d.card(1018, 316, 224, 126, "SealedSecret", "비대칭 암호화 Git 저장\n부트스트랩 시크릿 보호", "kubernetes.png", COL_INFRA, "Git Safe")
    d.card(1256, 316, 214, 126, "Keycloak", "OIDC SSO · TF RBAC\n네임스페이스 최소 권한", "keycloak.png", COL_APP, ":30880")

    # Layer 4: Zero-Trust Network & Service Mesh (y=492, h=144)
    d.zone(36, 492, 1448, 144, "Layer 4: 제로 트러스트 네트워크 & 서비스 메시 (L3/L4/L7 Policy & mTLS)", "파드 간 기본 차단 후 최소 경로만 허용", COL_DATA, "IaC + MW", icon="istio.png")
    d.card(52, 546, 452, 76, "CiliumNetworkPolicy (eBPF L3/L4/L7)", "Default-Deny 후 DNS(:53) + 최소 포트·HTTP 메서드만 허용", "cilium.png", COL_DATA, "L7 Drop")
    d.card(534, 546, 452, 76, "Istio Service Mesh (PeerAuth STRICT)", "Pod-to-Pod 자동 mTLS · SPIFFE X.509 신원 검증", "envoy.png", COL_APP, "STRICT mTLS")
    d.card(1016, 546, 452, 76, "OpenSSL 자체 CA + Nginx TLS 1.3", "server-chain.crt HTTPS(:443) 종료 · cert-renew.sh 갱신", "cert-manager.png", COL_INFRA, "TLS 1.3")

    # Layer 5 + Phase 2 GCP Security (y=672, h=176)
    d.zone(36, 672, 996, 176, "Layer 5: 커널 런타임 방어 & 보안 SIEM (Cilium Tetragon + ES 8)", "컨테이너 침해 시 커널 즉시 SIGKILL", COL_SEC, "Runtime", icon="tetragon.png")
    d.card(52, 728, 470, 104, "Cilium Tetragon (eBPF TracingPolicy)", "비인가 쉘(execve /bin/sh, curl) · /etc/shadow 열람\n외부 리버스 쉘 소켓 커널 Hook에서 즉시 SIGKILL", "tetragon.png", COL_SEC, "SIGKILL")
    d.card(544, 728, 470, 104, "Elasticsearch 8 + Loki SIEM", "Tetragon 감사 로그 + Gatekeeper 차단 + Trivy CRD\n공격 시도→커널 SIGKILL→SIEM 경보 단일 추적", "elasticsearch.svg", COL_DATA, ":9200")

    d.zone(1056, 672, 428, 176, "Phase 2: GCP 보안 확장 (6안)", "클라우드 동일 정책 + 원격 SIEM", COL_CLOUD, "LearingGCP", dashed=True, icon="kyverno.png")
    d.card(1072, 728, 396, 104, "GKE Kyverno + Tetragon", "미서명 이미지 차단 + Tetragon 로그\nWireGuard로 M4 Max ES 8 SIEM 송신", "kyverno.png", COL_CLOUD, ":51871")

    d.arrow([(392, 228), (392, 264)], color=COL_SEC, label="① Admission", label_pos=(392, 246))
    d.arrow([(1128, 228), (1128, 264)], color=COL_APP, label="② Secret", label_pos=(1128, 246))
    d.arrow([(392, 456), (392, 492)], color=COL_DATA, label="③ mTLS/L7", label_pos=(392, 474))
    d.arrow([(1128, 456), (1128, 492)], color=COL_DATA)
    d.arrow([(534, 636), (534, 672)], color=COL_SEC, label="④ Runtime", label_pos=(534, 654))
    d.arrow([(1032, 760), (1056, 760)], color=COL_CLOUD, dashed=True, bidir=True)

    d.foundation(866)
    d.flush()
    return fid


# ===========================================================================
# 03-B: Attack Kill-Chain Real-Time Blocking Sequence
# ===========================================================================
def build_03b_killchain(mcp: FigCraftMCP) -> int:
    fid = new_frame(mcp, "03b-Attack-Block-Flow", "03b-proposal3-attack-block-sequence", 1520, 680)
    d = EnterpriseDiagram(mcp, fid, 1520, 680)
    d.header(
        "[03-B] 침해·오설정 시나리오별 5계층 실시간 차단 시퀀스 (Supply Chain → Kernel SIGKILL)",
        "공급망, 어드미션, L7 네트워크, 커널 시스템콜 4단계에서 비정상 행위를 즉시 차단하고 ES 8 SIEM에 기록한다",
        [("Zero-Trust Kill-Chain", COL_SEC), ("SIEM 감사 추적", COL_DATA)],
    )

    tracks = [
        ("시나리오 1: HIGH/CRITICAL CVE 또는 미서명 이미지 푸시", "Trivy CLI + Cosign 검증", "trivy.png", "CI 파이프라인 실패 + Harbor 적재 거부", "harbor.png", "Jenkins/GitHub Actions 알림", "jenkins.svg", COL_INFRA),
        ("시나리오 2: :latest 태그 또는 privileged:true 배포 시도", "OPA Gatekeeper / Kyverno", "opa.png", "API Server 403 Admission 즉시 거부", "kyverno.png", "ArgoCD OutOfSync 차단 기록", "argocd.png", COL_SEC),
        ("시나리오 3: 비인가 파드의 DELETE 호출 또는 DB 직접 우회 접근", "Cilium L7 + Istio mTLS", "cilium.png", "eBPF 소켓 계층 DROP (요청 도달 불가)", "istio.png", "Hubble UI DROPPED 실시간 캡처", "hubble.png", COL_APP),
        ("시나리오 4: 파드 내부 리버스 쉘(/bin/sh) · SA 토큰(/var/run/secrets) 탈취", "Cilium Tetragon TracingPolicy", "tetragon.png", "커널 kprobe 단계 즉시 프로세스 SIGKILL", "tetragon.png", "ES 8 SIEM + Grafana 경보 발송", "elasticsearch.svg", COL_SEC),
    ]
    ty = 96
    for s_atk, s_gate, i_gate, s_act, i_act, s_log, i_log, acc in tracks:
        d.zone(36, ty, 1448, 128, s_atk, "", acc)
        d.card(54, ty + 52, 410, 64, s_gate, "인라인 보안 게이트 탐지", i_gate, acc, "Detect")
        d.card(544, ty + 52, 430, 64, s_act, "자동 차단 및 격리 집행", i_act, COL_SEC, "Block")
        d.card(1054, ty + 52, 412, 64, s_log, "감사 증적 및 상관분석 연동", i_log, COL_DATA, "Audit")
        d.arrow([(464, ty + 84), (544, ty + 84)], color=acc)
        d.arrow([(974, ty + 84), (1054, ty + 84)], color=COL_SEC)
        ty += 144

    d.flush()
    return fid


# ===========================================================================
# 04-A: Declarative IaC 4-Stage Pipeline Topology
# ===========================================================================
def build_04_proposal4(mcp: FigCraftMCP) -> int:
    fid = new_frame(mcp, "04-IaC-GitOps-IDP", "04-proposal4-declarative-iac-gitops", 1520, 920)
    d = EnterpriseDiagram(mcp, fid, 1520, 920)
    d.header(
        "[04-A] 선언적 IaC 4단계 파이프라인 & Multi-Arch GitOps 셀프서비스 아키텍처",
        "clusters.json(SSOT)에서 Tart VM 부트스트랩 → Terraform 리소스 → Ansible 보안 → Buildx/ArgoCD 배포로 책임을 분리한다",
        [("4단계 책임 분리", COL_INFRA), ("Harbor :30400 표준화", COL_APP)],
    )

    # 4 Clean Columns top y=92, h=534
    d.zone(36, 92, 336, 534, "Stage 1: VM & K8s Base", "IaC_apple_sillicon", COL_INFRA, "01~06단계", icon="tart.png")
    d.card(52, 152, 304, 86, "clusters.json (SSOT)", "4-클러스터 10 VM 스펙 · CIDR 유일 정본", "kubernetes.png", COL_INFRA, "SSOT")
    d.card(52, 254, 304, 96, "Tart Hypervisor 10 VMs", "Ubuntu 24.04 ARM64(k8s-golden)\n15~20분 일괄 생성 · softnet 통신", "tart.png", COL_INFRA, "21C/68G")
    d.card(52, 366, 304, 96, "kubeadm v1.31 + Cilium", "containerd 1.7 + Hubble CNI 부트스트랩", "cilium.png", COL_DATA, "Base CNI")
    d.card(52, 478, 304, 128, "fix-cluster-ip-drift.sh", "Tart 재부팅 IP 변동 시 SAN·kubelet\nCilium 호스트·kubeconfig 자동 복구", "ansible.svg", COL_SEC, "Phase 2.5")

    d.zone(406, 92, 336, 534, "Stage 2: K8s 기본 선언", "Terraform >= 1.5.0", COL_APP, "TF IaC", icon="terraform.png")
    d.card(422, 152, 304, 102, "Multi-Cluster Providers", "platform/dev/staging/prod kubeconfig\nVM SSH 없이 원격 API(:6443) 호출", "terraform.png", COL_APP, "4 Aliases")
    d.card(422, 272, 304, 102, "Namespace & Quota", "환경별 Namespace, ResourceQuota\nLimitRange 상한 선언", "kubernetes.png", COL_APP, "Quota")
    d.card(422, 392, 304, 102, "Terraform RBAC & NetPol", "ServiceAccount · RoleBinding 최소권한\n기본 Default-Deny 정책", "opa.png", COL_SEC, "RBAC")
    d.card(422, 512, 304, 96, "tfstate 드리프트 검증", "terraform plan -detailed-exitcode\n0건 변경 상태 상시 확인", "terraform.png", COL_INFRA, "Plan=0")

    d.zone(776, 92, 336, 534, "Stage 3: 플랫폼 · 보안", "Ansible + Helm v3", COL_DATA, "Config", icon="ansible.svg")
    d.card(792, 152, 304, 102, "setup-cluster.yml", "Ansible 태그별(trivy, gatekeeper, vault)\nHelm 멱등 설치 실행", "ansible.svg", COL_DATA, "Playbook")
    d.card(792, 272, 304, 102, "Gatekeeper & Vault", "OCI Gatekeeper + Vault Agent Injector\n5대 보안 Constraint 배포", "vault.svg", COL_SEC, "Security")
    d.card(792, 392, 304, 102, "Observability · Velero", "monitoring-values · loki-values\nvelero-values + Scouter 차트 배포", "helm.png", COL_DATA, "Helm v3")
    d.card(792, 512, 304, 96, "Port · Overlay 정본화", "Harbor NodePort 30400 통일\n(17-install-harbor.sh 30500 불일치 해소)", "harbor.png", COL_INFRA, ":30400")

    d.zone(1146, 92, 338, 534, "Stage 4: Multi-Arch CD", "Buildx · Harbor · ArgoCD", COL_APP, "GitOps", icon="argocd.png")
    d.card(1162, 152, 306, 102, "Jenkins + GH Actions", "Trivy 스캔 + Docker Buildx\nlinux/arm64,linux/amd64 동시 빌드", "docker.svg", COL_APP, "Buildx")
    d.card(1162, 272, 306, 102, "Harbor + Docker Hub", "로컬 고속 풀(:30400) + GCP 공용 풀\n단일 매니페스트 태그 푸시", "harbor.png", COL_INFRA, "Registry")
    d.card(1162, 392, 306, 102, "ArgoCD v2.13.2 AppSet", "Kustomize/Helm overlays 기반\ndev → staging → prod 승격", "argocd.png", COL_APP, ":30800")
    d.card(1162, 512, 306, 96, "Auto-Sync & Self-Heal", "수동 변경(Drift) 감지 시\nGit 정본 상태로 자동 복원", "kubernetes.png", COL_DATA, "Reconcile")

    d.arrow([(372, 350), (406, 350)], color=COL_INFRA, label="①")
    d.arrow([(742, 350), (776, 350)], color=COL_APP, label="②")
    d.arrow([(1112, 350), (1146, 350)], color=COL_DATA, label="③")

    # Bottom Zone: Phase 2 LearingGCP IaC & Crossplane IDP (y=650, h=198)
    d.zone(36, 650, 1448, 198, "Phase 2: 추후 GCP IaC & Platform Engineering IDP 확장 (LearingGCP 제5안 · 제8안)", "Ephemeral 8분 랩 + Crossplane Claim 셀프서비스", COL_CLOUD, "Phase 2", dashed=True, icon="crossplane.png")
    d.card(52, 706, 444, 124, "Ephemeral All-in-One 랩 (제5안)", "make gcp-up(8분): TF → Dynamic Ansible → Helmfile → Argo\n평상시 M4 Max 유지 · 실습 주 25h만 Spot 가동(실지출 $28/월)", "gcp.svg", COL_CLOUD, "8m Deploy")
    d.card(538, 706, 444, 124, "Crossplane GCP IDP (제8안)", "개발자 YAML Claim PR(team-order.yaml) → ArgoCD 동기화\nGCS · Pub/Sub · GCP SA · 네임스페이스 24시간 Reconcile", "crossplane.png", COL_CLOUD, "Self-Service")
    d.card(1024, 706, 444, 124, "DORA 메트릭 & FinOps 가시화", "팀별 배포 빈도·변경 리드타임·실패율·MTTR Grafana 집계\nPR Revert 시 GCP 관리형 리소스 자동 회수로 과금 누수 차단", "grafana.png", COL_DATA, "DORA 4대지표")

    d.arrow([(740, 626), (740, 650)], color=COL_CLOUD, dashed=True, label="④ Cloud")

    d.foundation(866)
    d.flush()
    return fid


# ===========================================================================
# 04-B: Multi-Arch Promotion & Crossplane IDP Control Loop
# ===========================================================================
def build_04b_promotion(mcp: FigCraftMCP) -> int:
    fid = new_frame(mcp, "04b-GitOps-Crossplane", "04b-proposal4-env-promotion-crossplane-idp", 1520, 680)
    d = EnterpriseDiagram(mcp, fid, 1520, 680)
    d.header(
        "[04-B] Multi-Arch GitOps 환경 승격(dev → staging → prod) & Crossplane 셀프서비스 제어 루프",
        "동일한 arm64/amd64 컨테이너 태그가 환경을 승격하며, Phase 2에서는 Git PR Claim으로 GCP 자원을 직접 생성한다",
        [("Multi-Arch Promotion", COL_APP), ("Crossplane XR/Claim", COL_CLOUD)],
    )

    d.zone(36, 94, 1448, 254, "Track 1: Multi-Arch 컨테이너 빌드 & ArgoCD ApplicationSet 승격 파이프라인", "Single Manifest Tag Across M4 Max & GCP", COL_APP, "CD Pipeline")
    d.card(54, 160, 232, 164, "1. Docker Buildx", "arm64 + amd64 동시 빌드\nTrivy + Cosign 통과", "docker.svg", COL_INFRA, "CI Build")
    d.card(336, 160, 232, 164, "2. Harbor & Hub", "Harbor(:30400) 로컬 풀\nDocker Hub GCP 공용 풀", "harbor.png", COL_INFRA, ":30400")
    d.card(618, 160, 232, 164, "3. Dev (Auto)", "replicas=1 · Istio 카나리\n즉시 배포 및 기능 점검", "argocd.png", COL_APP, "10.20")
    d.card(900, 160, 250, 164, "4. Staging (k6 Gate)", "replicas=2 · k6 500 VU\nP99·카오스 검증 통과 필수", "k6.svg", COL_DATA, "10.30")
    d.card(1200, 160, 266, 164, "5. Prod (Manual PR)", "replicas=3 · Gatekeeper 5종\nHA 분산 + Manual Approve", "kubernetes.png", COL_SEC, "10.40")

    d.arrow([(286, 242), (336, 242)], color=COL_INFRA)
    d.arrow([(568, 242), (618, 242)], color=COL_APP)
    d.arrow([(850, 242), (900, 242)], color=COL_DATA)
    d.arrow([(1150, 242), (1200, 242)], color=COL_SEC)

    d.zone(36, 372, 1448, 280, "Track 2: LearingGCP 제8안 — Crossplane 기반 Golden Path 셀프서비스 IDP 제어 루프", "Infrastructure-from-Kubernetes", COL_CLOUD, "Phase 2 IDP", dashed=True, icon="crossplane.png")
    d.card(54, 444, 290, 174, "1. Developer Git PR", "team-order.yaml Claim 1건\nHelm Golden Path 렌더링", "github.svg", COL_INFRA, "Git PR")
    d.card(404, 444, 290, 174, "2. ArgoCD ApplicationSet", "PR Merge 감지 → Claim 동기화\nPR Revert 시 자원 자동 회수", "argocd.png", COL_APP, "GitOps")
    d.card(754, 444, 330, 174, "3. Crossplane Controller", "K8s CRD 상태 ↔ GCP 상태\n24시간 Reconcile 드리프트 복구", "crossplane.png", COL_CLOUD, "Provider")
    d.card(1144, 444, 322, 174, "4. 자동 생성 리소스 & DORA", "GCS · Pub/Sub · IAM + Tenant NS\nGrafana DORA 4대 지표 집계", "gcp.svg", COL_DATA, "Auto Clean")

    d.arrow([(344, 531), (404, 531)], color=COL_INFRA)
    d.arrow([(694, 531), (754, 531)], color=COL_CLOUD)
    d.arrow([(1084, 531), (1144, 531)], color=COL_DATA)

    d.flush()
    return fid


# ===========================================================================
# 05-A: SRE Traffic Control, Chaos, HA & DR Topology
# ===========================================================================
def build_05_proposal5(mcp: FigCraftMCP) -> int:
    fid = new_frame(mcp, "05-SRE-Chaos-HA-DR", "05-proposal5-sre-chaos-ha-dr", 1520, 920)
    d = EnterpriseDiagram(mcp, fid, 1520, 920)
    d.header(
        "[05-A] 대규모 트래픽 제어(k6 · Istio · HPA · Saga) & Active-Active 이중화 · 백업/DR",
        "IaC_apple_sillicon 부하/HPA/Velero와 Middleware_Hello 튜닝/장애훈련 및 service_infra Saga를 통합한다",
        [("k6 500 VU · Breaker", COL_APP), ("Velero RTO < 5m", COL_DATA)],
    )

    d.zone(36, 92, 464, 756, "1. 대규모 트래픽 제어 & 성능 튜닝", "부하 주입 → 서킷브레이커 → 오토스케일", COL_APP, "IaC + MW", icon="k6.svg")
    d.card(52, 152, 432, 114, "k6 단계별 부하 테스트 (16종 프리셋)", "평시 100 VU ↔ 피크 500 VU (300 RPS)\nSRE Dashboard(/analysis) 원클릭 CSV 리포팅", "k6.svg", COL_APP, "500 VU")
    d.card(52, 282, 432, 118, "Istio L7 트래픽 엔지니어링", "VirtualService Canary(v1 80% / v2 20%)\nOutlierDetection: 3회 5xx → 30초 즉시 격리", "istio.png", COL_SEC, "30s Eject")
    d.card(52, 416, 432, 118, "HPA + PodDisruptionBudget", "metrics-server CPU 50%: Nginx(3→10) 확장\nPDB minAvailable로 Drain 시 무중단 보장", "kubernetes.png", COL_APP, "HPA+PDB")
    d.card(52, 550, 432, 126, "WEB · WAS · DB 커넥션 풀 튜닝", "Nginx worker/keepalive · Tomcat maxThreads\nJVM Heap(-Xmx512m) · HikariCP 튜닝 비교", "tomcat.svg", COL_DATA, "Benchmark")
    d.card(52, 692, 432, 134, "AlertManager (:30903) 8대 알럿 룰", "HighCpuUsage · HighMemoryUsage · NodeNotReady\nPodCrashLooping · PodOOMKilled 실시간 경보", "prometheus.png", COL_SEC, ":30903")

    d.zone(538, 92, 474, 756, "2. 이중화 HA · 분산 정합성 · 백업/DR", "노드 장애 무중단 · Saga 보상 · 복구", COL_DATA, "prod HA", icon="velero.png")
    d.card(554, 152, 442, 146, "prod 멀티워커 Active-Active 이중화", "prod-worker1(2C/8G) + prod-worker2(2C/8G)\nAnti-Affinity + TopologySpread 분산 배치\nNginx LB & Tomcat 한 대 중단 시 0초 무중단", "nginx.svg", COL_APP, "HA 2-Node")
    d.card(554, 316, 442, 166, "RabbitMQ 4.0.5 Saga 트랜잭션 보상", "1. order.created → payment-service 멱등 결제\n2. product-service SELECT FOR UPDATE 차감\n3. 실패 시 order.cancelled 보상 발행 & DLQ 재처리", "rabbitmq.svg", COL_INFRA, "Saga/DLQ")
    d.card(554, 500, 442, 166, "Velero v1.10 + MinIO + etcdctl DR", "4개 클러스터 마스터 일 1회 etcdctl 스냅샷(5개 보관)\nVelero Schedule 기반 네임스페이스/PV 백업\n네임스페이스 고의 삭제 후 5분 내 Restore 검증", "velero.png", COL_DATA, "RTO < 5m")
    d.card(554, 684, 442, 144, "정량 검증 기준표 (SRE KPI)", "P95/P99 응답지연 & TPS 개선율(Tuning 전/후)\nIstio 5xx 3회 감지 1초 내 격리 · Velero RTO<5m", "grafana.png", COL_INFRA, "SLO Pass")

    d.zone(1050, 92, 434, 756, "3. 10대 카오스 훈련 & Phase 2 확장", "장애 재현 → MTTR 검증", COL_SEC, "10 Drills", icon="prometheus.png")
    drills = [
        ("① 워커 노드 정지 (tart stop)", "Active 잔존 노드로 0초 우회", "tart.png"),
        ("② Tomcat OOM Kill (-Xmx128m)", "PodOOMKilled Alert + HPA 증설", "tomcat.svg"),
        ("③ JVM GC Storm 지연 스파이크", "Scouter XLog 분석 → G1GC 튜닝", "scouter.png"),
        ("④ DB Connection Pool 고갈(504)", "Hikari/SQLAlchemy 풀 상한 조정", "mysql.svg"),
        ("⑤ RabbitMQ 브로커 중단/DLQ", "StatefulSet 복구 & 메시지 유실 0", "rabbitmq.svg"),
        ("⑥ Cilium L7 오설정 Drop", "Hubble UI(:31235) 1분 내 식별", "hubble.png"),
        ("⑦ 카나리 v2 500 오류 / DR 503", "Istio 격리 + Phase 2 아이오와 DR", "gcp.svg"),
    ]
    dy = 152
    for dt, ds, di in drills:
        d.card(1066, dy, 402, 74, dt, ds, di, COL_SEC)
        dy += 84

    d.card(1066, 748, 402, 80, "Phase 2: GCP Bursting & 멀티리전", "Cloud Bursting($32) · 서울↔아이오와 DR($39)\n세부 흐름은 다이어그램 [05-B] 참조", "gcp.svg", COL_CLOUD, "LearingGCP")

    d.arrow([(500, 210), (538, 210)], color=COL_APP, label="Load")
    d.arrow([(500, 340), (538, 390)], color=COL_SEC, label="Breaker")
    d.arrow([(1012, 390), (1050, 390)], color=COL_SEC, bidir=True, label="Chaos")

    d.foundation(866)
    d.flush()
    return fid


# ===========================================================================
# 05-B: Phase 2 Cloud Bursting & Multi-Region DR Flow
# ===========================================================================
def build_05b_bursting_dr(mcp: FigCraftMCP) -> int:
    fid = new_frame(mcp, "05b-Bursting-MultiRegion", "05b-proposal5-bursting-multiregion-failover", 1520, 680)
    d = EnterpriseDiagram(mcp, fid, 1520, 680)
    d.header(
        "[05-B] Phase 2: GCP Cloud Bursting(1안) & 서울↔아이오와 3각 멀티리전 무중단 DR(4안)",
        "평시 M4 Max($0) 처리 → 500 VU 시 서울 GKE Bursting → 서울 리전 전면 장애 시 1초 내 아이오와 리전 Failover",
        [("Bursting: 실지출 $32/월", COL_CLOUD), ("Multi-Region RTO < 5s", COL_SEC)],
    )

    d.zone(36, 94, 444, 558, "거점 1: M4 Max Control & DB Vault", "클라우드 비용 $0 · 영구 백업/관측", COL_INFRA, "On-Prem $0", icon="apple.svg")
    d.card(52, 156, 412, 92, "평시 트래픽 (100 VU 이하)", "로컬 Tart prod 클러스터 100% 처리", "kubernetes.png", COL_APP, "100 VU")
    d.card(52, 268, 412, 92, "고비용 Stateful DB 상주", "PostgreSQL 16 · MySQL 8 · Redis 7 · RabbitMQ", "postgresql.svg", COL_DATA, "FinOps $0")
    d.card(52, 380, 412, 92, "Global 관측소 & k6 컨트롤러", "Scouter · Prom · Grafana(:30300) · k6", "scouter.png", COL_DATA, "M4 Max")
    d.card(52, 492, 412, 140, "Velero + etcd 로컬 백업 금고", "MinIO(:9000) 백업본 → GCS 버킷 이중 소산\n호스트 장애 시에도 상태 100% 보존", "velero.png", COL_INFRA, "MinIO")

    d.zone(540, 94, 444, 558, "거점 2: GCP 서울 (asia-northeast3-a)", "Primary Edge · RTT ~8ms", COL_CLOUD, "Primary", dashed=True, icon="gcp.svg")
    d.card(556, 156, 412, 108, "GKE Zonal Spot (1 → 3 Bursting)", "Control Plane 무료($0) · e2-standard-2 Spot\n피크 500 VU 시 HPA/ClusterMesh 자동 확장", "gcp.svg", COL_CLOUD, "Spot 1→3")
    d.card(556, 282, 412, 108, "Istio Ingress + East-West (:15443)", "Cloud LB(:443) 종료 · Locality LB Failover\n평시 서울 처리, 임계치 초과/장애 시 우회", "istio.png", COL_APP, ":15443")
    d.card(556, 408, 412, 108, "Cilium ClusterMesh + WireGuard", "10.10(M4) ↔ 10.20(서울) ↔ 10.30(아이오와)\nGlobal Service로 M4 Max DB 직접 호출", "cilium.png", COL_DATA, ":51871/:2379")
    d.card(556, 534, 412, 98, "카오스 장애 주입 (HTTP 503 Abort)", "Istio Fault Injection 또는 서울 노드 Drain", "prometheus.png", COL_SEC, "503 Abort")

    d.zone(1044, 94, 440, 558, "거점 3: GCP 아이오와 (us-central1-a)", "Secondary DR · RTT ~140ms", COL_SEC, "DR < 5s", dashed=True, icon="gcp.svg")
    d.card(1060, 156, 408, 108, "아이오와 Spot DR 클러스터", "서울 대비 25% 저렴한 Spot 단가\nStandby WAS/MSA 장애 시 즉시 Scale-up", "gcp.svg", COL_CLOUD, "$10/mo")
    d.card(1060, 282, 408, 108, "1초 내 자동 Failover (OutlierDetection)", "서울 연속 5xx 3회 감지 시 태평양 횡단 우회\n전체 재해복구 RTO < 5초 검증", "envoy.png", COL_SEC, "RTO < 5s")
    d.card(1060, 408, 408, 108, "PostgreSQL Read Replica WAL 복제", "WireGuard 암호화 터널로 비동기 스트리밍\n서울(8ms) vs 아이오와(140ms) XLog 지연 비교", "postgresql.svg", COL_DATA, ":5432")
    d.card(1060, 534, 408, 98, "GCP Cloud Storage (GCS) 오프사이트", "Velero · etcd · ES8 스냅샷 클라우드 영구 보관", "velero.png", COL_INFRA, "GCS DR")

    d.arrow([(480, 210), (540, 210)], color=COL_CLOUD, bidir=True, label="Burst")
    d.arrow([(480, 456), (540, 456)], color=COL_DATA, bidir=True, label=":51871")
    d.arrow([(984, 336), (1044, 336)], color=COL_SEC, dashed=True, label="Failover")
    d.arrow([(984, 580), (1044, 580)], color=COL_DATA, dashed=True, label="GCS Sync")

    d.flush()
    return fid


# ===========================================================================
# 06-A: MicroVM Hybrid Bridge & AI Sandbox Topology
# ===========================================================================
def build_06_proposal6(mcp: FigCraftMCP) -> int:
    fid = new_frame(mcp, "06-MicroVM-GCP-Bridge", "06-proposal6-microvm-gcp-bridge", 1520, 920)
    d = EnterpriseDiagram(mcp, fid, 1520, 920)
    d.header(
        "[06-A] 다중 컨테이너 런타임(runc + Firecracker MicroVM) & M4 Max ↔ GCP 하이브리드 브릿지",
        "ARM64 M4 Max의 /dev/kvm 제약을 GCP Cascade Lake N2 Nested KVM과 WireGuard/ClusterMesh로 연결한다 (LearingGCP 3·7안)",
        [("runc vs kata-fc", COL_SEC), ("ARM64 ↔ x86_64 Mesh", COL_CLOUD)],
    )

    d.zone(36, 92, 444, 756, "Phase 1: M4 Max (ARM64 로컬 베이스)", "빌드 · DB · 관제 · AI 추론 ($0)", COL_INFRA, "ARM64 $0", icon="apple.svg")
    d.card(52, 152, 412, 108, "Tart Ubuntu 24.04 ARM64", "10대 K8s 노드 · containerd 1.7 CRI(runc)\nARM64 VM 내부 x86 Nested KVM 제약 존재", "tart.png", COL_INFRA, "ARM64")
    d.card(52, 276, 412, 108, "Docker Buildx Multi-Arch CI", "docker buildx --platform arm64,amd64\n단일 태그로 로컬·GCP 이기종 동시 배포", "docker.svg", COL_APP, "Multi-Arch")
    d.card(52, 400, 412, 108, "로컬 CRI 격리 베이스라인", "seccomp 프로파일 + AppArmor + Tetragon\n컨테이너 런타임 보안 정책 사전 검증", "tetragon.png", COL_SEC, "Seccomp")
    d.card(52, 524, 412, 114, "Control Tower & 벤치마크 저장소", "ArgoCD · Prom · Grafana · ES 8\nrunc vs kata-fc 50개 파드 부팅/RAM 실측", "grafana.png", COL_DATA, "Metrics")
    d.card(52, 654, 412, 174, "Local Stateful DB & AI-Ops (7안)", "PG · Redis · RabbitMQ 로컬 상시 유지($0)\n128GB Metal GPU LLM(Ollama :11434) 및\n비신뢰 AI 코드 실행 요청을 GCP N2로 위임", "postgresql.svg", COL_INFRA, "LLM+DB")

    d.zone(530, 92, 360, 756, "M4 Max ↔ GCP 하이브리드 브릿지", "이기종 클러스터 L3/L7 단일 메시", COL_CLOUD, "Bridge", icon="wireguard.svg")
    d.card(546, 152, 328, 128, "WireGuard Kernel VPN", "UDP :51871 / :51820 암호화\nM4 Max NAT → GCP 공인 IP\n아웃바운드 직결 L3 터널", "wireguard.svg", COL_SEC, ":51871")
    d.card(546, 298, 328, 134, "Cilium ClusterMesh", "TCP :2379 ETCD 상태 동기화\nM4(10.10) ↔ GCP(10.50) IP 직결\nGlobal Service 자동 디스커버리", "cilium.png", COL_DATA, ":2379")
    d.card(546, 450, 328, 134, "Istio East-West Gateway", "TCP :15443 SNI mTLS 터널\n신뢰 앱→로컬 runc / 비신뢰→\nGCP kata-fc 런타임 기반 라우팅", "istio.png", COL_APP, ":15443")
    d.card(546, 602, 328, 226, "Terraform + Ansible KVM 자동화", "1. TF: Cascade Lake N2 Spot\n   (enable_nested_virtualization)\n2. Ansible 무인 구성:\n   • /dev/kvm 장치 권한 설정\n   • LVM devmapper thinpool\n   • containerd kata-fc 등록", "ansible.svg", COL_INFRA, "Auto IaC")

    d.zone(940, 92, 544, 756, "Phase 2 (GCP): x86_64 Nested KVM + Firecracker MicroVM", "n2-standard-4 Spot (/dev/kvm · ~$0.045/h)", COL_CLOUD, "LearingGCP 3·7안", dashed=True, icon="firecracker.png")
    d.card(956, 152, 512, 84, "containerd 1.7 CRI + LVM devmapper Thinpool", "Pod spec.runtimeClassName 1줄로 runc vs kata-fc 핸들러 분기", "containerd.png", COL_INFRA, "CRI Switch")

    d.subpanel(956, 252, 248, 270, "runc (신뢰 데몬)", "Host Kernel 공유", COL_APP)
    d.card(966, 286, 228, 72, "runc Kernel", "Namespaces · 커널 6.8 공유", "kubernetes.png", COL_APP, "Host OS")
    d.card(966, 368, 228, 74, "DaemonSet Pods", "Cilium·Tetragon·Envoy", "cilium.png", COL_INFRA, "System")
    d.card(966, 452, 228, 60, "한계: 커널 공유", "비신뢰 코드 탈출 위험", "trivy.png", COL_SEC)

    d.subpanel(1220, 252, 248, 270, "kata-fc (격리 VMM)", "125ms MicroVM", COL_SEC)
    d.card(1230, 286, 228, 72, "Guest Kernel", "하드웨어 /dev/kvm 분리", "firecracker.png", COL_SEC, "125ms")
    d.card(1230, 368, 228, 74, "AI Sandbox", "실행 후 MicroVM 즉시 파기", "kata.png", COL_SEC, "kata-fc")
    d.card(1230, 452, 228, 60, "uname -r 분리", "50개 부팅·RAM 실측", "k6.svg", COL_DATA)

    d.card(956, 538, 512, 134, "Cilium eBPF (tc-redirect-tap) 제로카피 네트워킹", "Cilium veth 패킷을 Firecracker virtio-net TAP 장치에 eBPF TC 필터로 직접 전달\nL7 NetworkPolicy · Istio mTLS 그대로 상속 & 메트릭 WireGuard 역전송", "cilium.png", COL_DATA, "tc-tap")
    d.card(956, 688, 512, 140, "FinOps & 아키텍처 설계 의도", "1. 비실습 시간 GCE Spot 정지(STOP)로 컴퓨팅 비용 $0 유지 (월 $10 크레딧 내 운용)\n2. M4 Max(ARM64)와 GCP N2(x86 KVM)를 결합해 CRI→LVM→/dev/kvm 전 계층 실증", "gcp.svg", COL_CLOUD, "Stop=$0")

    d.arrow([(480, 216), (530, 216)], color=COL_SEC, bidir=True, label=":51871")
    d.arrow([(480, 364), (530, 364)], color=COL_DATA, bidir=True, label=":2379")
    d.arrow([(480, 516), (530, 516)], color=COL_APP, bidir=True, label=":15443")
    d.arrow([(890, 216), (940, 216)], color=COL_CLOUD, dashed=True, bidir=True)
    d.arrow([(890, 364), (940, 364)], color=COL_DATA, dashed=True, bidir=True)
    d.arrow([(890, 516), (940, 516)], color=COL_APP, dashed=True, bidir=True)

    d.foundation(866)
    d.flush()
    return fid


# ===========================================================================
# 06-B: containerd CRI runc vs Firecracker kata-fc Internals
# ===========================================================================
def build_06b_internals(mcp: FigCraftMCP) -> int:
    fid = new_frame(mcp, "06b-CRI-Firecracker", "06b-proposal6-runc-vs-kata-firecracker-internals", 1520, 680)
    d = EnterpriseDiagram(mcp, fid, 1520, 680)
    d.header(
        "[06-B] containerd 1.7 CRI 런타임 분기(runc vs kata-fc Firecracker) 커널 · 스토리지 · 네트워크 내부 구조",
        "Pod YAML의 runtimeClassName 1줄에 따라 호스트 커널 공유(runc)와 125ms 독립 게스트 커널(Firecracker)로 분기한다",
        [("CRI → VMM Plumbing", COL_SEC), ("tc-redirect-tap · devmapper", COL_DATA)],
    )

    d.zone(36, 92, 1448, 128, "상위 CRI 분기 계층 (GCP Cascade Lake N2 Host · /dev/kvm 활성)", "kubelet → containerd 1.7 RuntimeClass Switch", COL_INFRA, "CRI Switch", icon="containerd.png")
    d.card(56, 142, 430, 64, "kube-apiserver (:6443) & kubelet", "Pod 스펙 spec.runtimeClassName 검사", "kubernetes.png", COL_INFRA, "Schedule")
    d.card(546, 142, 430, 64, "containerd 1.7 CRI Daemon", "/etc/containerd/config.toml 런타임 라우팅", "containerd.png", COL_INFRA, "CRI v1")
    d.card(1036, 142, 428, 64, "LVM devmapper Thinpool + CNI", "블록 스냅샷 마운트 & Cilium veth 생성", "cilium.png", COL_DATA, "Plumbing")
    d.arrow([(486, 174), (546, 174)], color=COL_INFRA)
    d.arrow([(976, 174), (1036, 174)], color=COL_DATA)

    # Left Branch: runc (x=36, y=246, w=700, h=406)
    d.zone(36, 246, 700, 406, "경로 A: 표준 컨테이너 (runtimeClassName: runc)", "Linux Namespaces + cgroups", COL_APP, "Default runc", icon="docker.svg")
    d.card(54, 304, 664, 68, "containerd-shim-runc-v2", "호스트 OS 프로세스로 컨테이너 직접 생성 (~수십 ms 기동)", "containerd.png", COL_APP, "Shim v2")
    d.card(54, 384, 324, 78, "Namespaces · seccomp", "프로세스·네트워크 논리 격리", "trivy.png", COL_INFRA, "Soft Isolation")
    d.card(394, 384, 324, 78, "Trusted System Pods", "Istio Envoy · Tetragon · Prom Agent", "cilium.png", COL_APP, "DaemonSet")
    d.card(54, 474, 664, 78, "Shared Host Linux Kernel (6.8.0-gcp) + OverlayFS", "모든 일반 파드가 단일 호스트 커널을 직접 공유 (커널 취약점 탈출 시 전체 위험)", "kubernetes.png", COL_SEC, "Shared Kernel")
    d.card(54, 564, 664, 74, "Direct veth Pair → Cilium eBPF TC", "가상화 변환 없이 호스트 네트워크 네임스페이스 직접 연결", "envoy.png", COL_DATA, "Native Net")

    # Right Branch: kata-fc Firecracker (x=784, y=246, w=700, h=406)
    d.zone(784, 246, 700, 406, "경로 B: Firecracker MicroVM (runtimeClassName: kata-fc)", "하드웨어 /dev/kvm 독립 커널", COL_SEC, "125ms MicroVM", icon="firecracker.png")
    d.card(802, 304, 664, 68, "containerd-shim-kata-v2 + Firecracker VMM (v1.9)", "/dev/kvm (Intel VT-x) 통해 경량 VMM 프로세스 ~125ms 부팅", "firecracker.png", COL_SEC, "/dev/kvm")
    d.card(802, 384, 324, 78, "Guest Kernel (6.1.62)", "파드마다 별도 Linux 커널", "kata.png", COL_SEC, "Hard Isolation")
    d.card(1142, 384, 324, 78, "kata-agent (vsock 제어)", "LLM AI 코드 · 멀티테넌트 실행 후 파기", "opentelemetry.png", COL_CLOUD, "AI Sandbox")
    d.card(802, 474, 324, 78, "virtio-blk (devmapper)", "virtio-fs 배제 · 블록 전용 마운트", "containerd.png", COL_DATA, "Block Snapshot")
    d.card(1142, 474, 324, 78, "virtio-net (tc-redirect)", "eBPF TC로 veth→TAP 제로카피", "cilium.png", COL_DATA, "Zero-Copy TAP")
    d.card(802, 564, 664, 74, "보안 · 네트워크 완전 호환", "호스트 커널과 하드웨어 단절 상태에서도 Cilium Policy · Istio mTLS 동일 적용", "tetragon.png", COL_INFRA, "Full Mesh")

    d.arrow([(386, 220), (386, 246)], color=COL_APP, label="runc")
    d.arrow([(1134, 220), (1134, 246)], color=COL_SEC, label="kata-fc")

    d.flush()
    return fid


# ===========================================================================
# Overview Canvas: All Proposals + Official Icons Grid
# ===========================================================================
def build_overview_page(mcp: FigCraftMCP) -> int:
    fid = new_frame(mcp, "Overview-Canvas", "all-proposals-overview", 1520, 880)
    d = EnterpriseDiagram(mcp, fid, 1520, 880)
    d.header(
        "vol1_Infra 통합 아키텍처 맵 — 4개 로컬 레포지토리 + LearingGCP 통합 구성",
        "기존 4개 프로젝트 자산을 단일 4-클러스터 플랫폼(00)과 6대 아키텍처 제안(01~06 · 각 구조도+흐름도 2종)으로 체계화한다",
        [("4 Local Repos + LearingGCP", COL_INFRA), ("15 Diagrams · 4 Personas", COL_APP)],
    )

    # Top Row: Source Assets (y=90, h=134)
    d.zone(36, 90, 1448, 134, "입력 자산: 4개 기존 레포지토리 + LearingGCP(클론 검증 완료)", "중복 제거 및 상호 보완", COL_INFRA, "As-Is", icon="github.svg")
    sources = [
        ("IaC_apple_sillicon", "Tart 10 VM · K8s v1.31 · SRE UI", "tart.png", COL_INFRA, "Base Infra"),
        ("devsecops", "Terraform · Ansible · Trivy · Vault", "trivy.png", COL_SEC, "SecOps"),
        ("Middleware_Hello", "Nginx · Tomcat 10 · MySQL · Scouter", "tomcat.svg", COL_APP, "3-Tier"),
        ("service_infra", "Kong · 8-MSA · PG/Rabbit/ES · Jaeger", "fastapi.svg", COL_DATA, "8-MSA"),
        ("LearingGCP (8안)", "Tetragon · Firecracker · DR · LLM · IDP", "gcp.svg", COL_CLOUD, "Phase 2"),
    ]
    sx = 50
    for sn, sr, si, sa, sb in sources:
        d.card(sx, 144, 274, 68, sn, sr, si, sa, sb, icon_size=36)
        sx += 286

    # Middle Banner: [00] Master Platform (y=246, h=116)
    d.zone(36, 246, 1448, 116, "[00] 마스터 통합 플랫폼 — 단일 4-클러스터 (platform · dev · staging · prod)", "Phase 1 M4 Max ($0) → Phase 2 GCP 확장", COL_APP, "00-master", icon="kubernetes.png")
    clusters = [
        ("Platform (10.10)", "관제 Lake + CI/CD + Vault/Velero", "grafana.png", COL_DATA),
        ("Dev (10.20)", "Istio mTLS + Keycloak + HPA + Trivy", "istio.png", COL_APP),
        ("Staging (10.30)", "k6 500 VU + 10대 카오스 벤치마크", "k6.svg", COL_INFRA),
        ("Prod (10.40)", "Track A/B 공존 + Gatekeeper/Tetragon", "nginx.svg", COL_SEC),
        ("Phase 2 (GCP)", "WireGuard + GKE Spot + N2 KVM + DR", "gcp.svg", COL_CLOUD),
    ]
    cx = 50
    for cn, cs, ci, ca in clusters:
        d.compact_card(cx, 298, 274, 54, cn, cs, ci, ca)
        cx += 286

    for ax in [187, 473, 759, 1045, 1331]:
        d.arrow([(ax, 224), (ax, 246)], color=COL_INFRA)

    # Bottom 2x3 Grid: Proposals 01~06 (y=386..804)
    cards = [
        ("01. 레거시 3-Tier + 8-MSA 통합", "Nginx·Tomcat HA·MySQL ↔ Kong·FastAPI 8-MSA\nKeycloak SSO 단일 인증 & Strangler Fig 브릿지", ["nginx.svg", "tomcat.svg", "kong.svg", "fastapi.svg", "keycloak.png"], COL_APP, "01-hybrid-middleware-msa-platform.md"),
        ("02. Scouter · OTel · Hubble 관제", "Scouter XLog + Jaeger OTel + Prom + Hubble\nLoki vs Elasticsearch 8 듀얼 로그 정량 비교", ["scouter.png", "jaeger.png", "prometheus.png", "hubble.png", "loki.png"], COL_DATA, "02-360-apm-observability-center.md"),
        ("03. 5계층 Zero-Trust DevSecOps", "Trivy·Cosign·Harbor → Gatekeeper 5종 → Vault\n→ Cilium L7 · Istio mTLS → Tetragon SIGKILL", ["trivy.png", "harbor.png", "opa.png", "vault.svg", "tetragon.png"], COL_SEC, "03-zero-trust-devsecops-tetragon.md"),
        ("04. 선언적 IaC & GitOps IDP", "clusters.json → Tart → Terraform → Ansible\nBuildx Multi-Arch → ArgoCD · Crossplane IDP", ["tart.png", "terraform.png", "ansible.svg", "argocd.png", "crossplane.png"], COL_INFRA, "04-declarative-iac-gitops-idp.md"),
        ("05. SRE 부하제어 · HA · 멀티리전 DR", "k6 500 VU · Istio Breaker · HPA · RabbitMQ Saga\nVelero(RTO<5m) & 서울↔아이오와 DR(RTO<5s)", ["k6.svg", "istio.png", "rabbitmq.svg", "velero.png", "gcp.svg"], COL_DATA, "05-sre-chaos-ha-dr-engineering.md"),
        ("06. Firecracker MicroVM & 브릿지", "containerd runc vs 125ms 독립 커널 kata-fc\nWireGuard + ClusterMesh M4↔GCP (+7안 AI)", ["containerd.png", "firecracker.png", "kata.png", "wireguard.svg", "cilium.png"], COL_CLOUD, "06-microvm-firecracker-gcp-bridge.md"),
    ]
    for idx, (ct, cd, cicons, ca, cdoc) in enumerate(cards):
        col, row = idx % 3, idx // 3
        px = 36 + col * 492
        py = 386 + row * 218
        d.zone(px, py, 464, 200, ct, "", ca, f"0{idx+1} (2도표)", icon=cicons[0])
        d.text(px + 16, py + 54, cd, size=11.0, color=SLATE_SUB, width=432)
        d.flush()
        ix = px + 16
        for ic in cicons:
            d.mcp.place_icon(ic, d.root, ix, py + 106, box_size=34, icon_pad=3, badge_radius=6)
            ix += 44
        d.step_badge(px + 16, py + 150, 432, 36, f"문서: proposal/{cdoc}", cicons[0], ca)
        if row == 0:
            d.arrow([(px + 232, 362), (px + 232, 386)], color=ca)

    d.foundation(822)
    d.flush()
    return fid


def main() -> int:
    if not FIGCRAFT_CLI.exists():
        print(f"ERROR: figcraft-cli not found at {FIGCRAFT_CLI}", file=sys.stderr)
        return 1

    DIAGRAMS_DIR.mkdir(parents=True, exist_ok=True)
    mcp = FigCraftMCP(FIGCRAFT_CLI, ROOT_DIR)

    try:
        frames = [
            ("00-master-integration-architecture", build_00_master(mcp), True),
            ("00b-as-is-to-be-consolidation", build_00b_consolidation(mcp), True),
            ("01-proposal1-hybrid-middleware-msa", build_01_proposal1(mcp), True),
            ("01b-proposal1-request-sso-strangler-flow", build_01b_flow(mcp), True),
            ("02-proposal2-360-apm-observability", build_02_proposal2(mcp), True),
            ("02b-proposal2-mttr-correlation-pipeline", build_02b_correlation(mcp), True),
            ("03-proposal3-zero-trust-devsecops", build_03_proposal3(mcp), True),
            ("03b-proposal3-attack-block-sequence", build_03b_killchain(mcp), True),
            ("04-proposal4-declarative-iac-gitops", build_04_proposal4(mcp), True),
            ("04b-proposal4-env-promotion-crossplane-idp", build_04b_promotion(mcp), True),
            ("05-proposal5-sre-chaos-ha-dr", build_05_proposal5(mcp), True),
            ("05b-proposal5-bursting-multiregion-failover", build_05b_bursting_dr(mcp), True),
            ("06-proposal6-microvm-gcp-bridge", build_06_proposal6(mcp), True),
            ("06b-proposal6-runc-vs-kata-firecracker-internals", build_06b_internals(mcp), True),
            ("all-proposals-overview", build_overview_page(mcp), False),
        ]

        figcraft_path = "proposal/assets/diagrams/vol1-infra-proposals.figcraft"
        save_res = mcp.tool("save_file", {"path": figcraft_path})
        print(f"[Saved .figcraft] {save_res}")

        for name, fid, export_svg in frames:
            png_path = f"proposal/assets/diagrams/{name}.png"
            res_png = mcp.tool("export", {"ids": [fid], "format": "png", "scale": 2, "path": png_path})
            print(f"[Exported PNG] {png_path} ({res_png.get('bytes')} bytes)")
            if export_svg:
                svg_path = f"proposal/assets/diagrams/{name}.svg"
                res_svg = mcp.tool("export", {"ids": [fid], "format": "svg", "path": svg_path})
                print(f"[Exported SVG] {svg_path} ({res_svg.get('bytes')} bytes)")

    finally:
        mcp.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
