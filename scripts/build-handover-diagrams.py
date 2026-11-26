#!/usr/bin/env python3
"""
Generate academic-paper-style 16:9 PPT Layer-Stack architecture diagrams (1600x900 @2x PNG/SVG) via FigCraft MCP.

Visual design grammar (Pure Black-on-White Research Paper Monochrome Style):
  - Pure white slide canvas (#FFFFFF) and pure white boxes (#FFFFFF)
  - Crisp black borders (#000000) with sharp architectural corners (radius=0)
  - Pure black ink (#000000) across ALL typography, dividers, AND all 27 official open-source icons
  - Strict Bottom-Up vertical layering:
      L0 Hardware (M4 Max 16C / 128GB) -> L1 Hypervisor (Tart v2.31.0) -> L2 VMs -> L3 OS/Runtime -> L4~L6 Platform/Apps
  - Layer-split 6-slide deck:
      slide-01-full-stack-architecture        : Fig. 1 Full Bottom-Up Stack (L0 -> L6)
      slide-02-l0-l4-ops-cp-iac-stack         : Fig. 2 Lower & Control Layer Split (L0~L4 IaC + ops + cp-1..3)
      slide-03-l5-l6-network-workers          : Fig. 3 Upper Cluster Layer Split (L4~L6 Net + 4 Platform + order-service)
      slide-04-ops-lifecycle-and-demos        : Fig. 4 Daily Makefile Loop & 6 Verified Scenarios
      slide-05-tech-stack-roles-infra-core    : Fig. 5 Tech Stack Role Catalog 1/2 (L0~L4 Infra, Ops & K8s Core)
      slide-06-tech-stack-roles-platform-app  : Fig. 6 Tech Stack Role Catalog 2/2 (L5~L6 GitOps, SecOps, DR, Obs & App)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from PIL import Image

ROOT_DIR = Path(__file__).resolve().parents[1]
FIGCRAFT_CLI = ROOT_DIR / ".tools" / "bin" / "figcraft-cli"
ICON_SRC_ARCHIVE = ROOT_DIR / "archive" / "v1-integration-proposal" / "proposal" / "assets" / "icons"
ICON_SRC_HANDOVER = ROOT_DIR / "docs" / "diagrams" / "icons"
ICON_PNG_CACHE = ROOT_DIR / ".runtime" / "handover-icons" / "png"
DIAGRAMS_DIR = ROOT_DIR / "docs" / "diagrams"

SLIDE_W = 1600
SLIDE_H = 900
FONT_FAMILY = "Apple SD Gothic Neo"

BG_WHITE = "#FFFFFF"
STROKE_DARK = "#000000"
STROKE_MID = "#000000"
TEXT_MAIN = "#000000"
TEXT_SUB = "#000000"

# Strict paper monochrome fills & black borders everywhere (zero color pixels)
FILL_HW = "#FFFFFF"
FILL_HV = "#FFFFFF"
FILL_VM_OPS = "#FFFFFF"
FILL_VM_CP = "#FFFFFF"
FILL_VM_WK = "#FFFFFF"
FILL_SEC = "#FFFFFF"
FILL_OBS = "#FFFFFF"
FILL_NET = "#FFFFFF"
FILL_APP = "#FFFFFF"

ACC_HW = "#000000"
ACC_HV = "#000000"
ACC_OPS = "#000000"
ACC_CP = "#000000"
ACC_NET = "#000000"
ACC_WK = "#000000"
ACC_SEC = "#000000"
ACC_OBS = "#000000"
ACC_RED = "#000000"


def _convert_icon_to_bw(name: str, png_path: Path) -> None:
    """Convert any open-source PNG logo into crisp pure black (#000000) & white (#FFFFFF) ink on transparent background."""
    im = Image.open(png_path).convert("RGBA")
    if max(im.size) > 256:
        im.thumbnail((256, 256), Image.Resampling.LANCZOS)
    px = im.load()
    iw, ih = im.size
    for y in range(ih):
        for x in range(iw):
            r, g, b, a = px[x, y]
            if a < 20:
                px[x, y] = (0, 0, 0, 0)
                continue
            lum = 0.299 * r + 0.587 * g + 0.114 * b
            sat = max(r, g, b) - min(r, g, b)
            if name == "tart":
                px[x, y] = (0, 0, 0, a) if lum < 205 else (255, 255, 255, a)
            elif name == "cncf-argo":
                if (sat < 28 and lum > 220) or lum > 182:
                    px[x, y] = (255, 255, 255, a)
                else:
                    px[x, y] = (0, 0, 0, a)
            elif name == "seaweedfs":
                is_bg_blue = b > r + 40 and b > g + 15 and r < 70
                border = x < 10 or x > iw - 11 or y < 10 or y > ih - 11
                if border or lum < 52:
                    px[x, y] = (0, 0, 0, a)
                elif is_bg_blue:
                    px[x, y] = (255, 255, 255, a)
                else:
                    px[x, y] = (0, 0, 0, a)
            else:
                px[x, y] = (255, 255, 255, a) if (sat < 35 and lum > 190) else (0, 0, 0, a)
    im.save(png_path)


def prepare_icon_cache() -> dict[str, str]:
    ICON_PNG_CACHE.mkdir(parents=True, exist_ok=True)
    svg_sources: dict[str, Path] = {}
    png_sources: dict[str, Path] = {}
    for directory in (ICON_SRC_ARCHIVE, ICON_SRC_HANDOVER):
        if not directory.exists():
            continue
        for p in sorted(directory.iterdir()):
            if not p.is_file():
                continue
            if p.suffix.lower() == ".svg":
                svg_sources[p.stem] = p
            elif p.suffix.lower() == ".png":
                png_sources[p.stem] = p

    hap = ICON_SRC_HANDOVER / "haproxy.svg"
    if hap.exists():
        txt = hap.read_text()
        if "fill=" not in txt:
            hap.write_text(txt.replace("<path ", '<path fill="#000000" ', 1))

    needed = [
        "apple",
        "tart",
        "terraform",
        "ansible",
        "docker",
        "haproxy",
        "seaweedfs",
        "trivy",
        "gitea",
        "vault",
        "k6",
        "kubernetes",
        "cilium",
        "envoy",
        "hubble",
        "cert-manager",
        "cncf-argo",
        "helm",
        "external-secrets",
        "kyverno",
        "postgresql",
        "velero",
        "fastapi",
        "prometheus",
        "loki",
        "opentelemetry",
        "grafana",
    ]
    prefer_png = {"cilium"}
    resolved: dict[str, str] = {}
    for name in needed:
        if name in prefer_png and name in png_sources:
            src = png_sources[name]
        else:
            src = svg_sources.get(name) or png_sources.get(name)
        if not src:
            raise FileNotFoundError(f"Missing official icon for '{name}'")
        dst = ICON_PNG_CACHE / f"{name}.png"
        if src.suffix.lower() == ".svg":
            subprocess.run(
                ["rsvg-convert", "-w", "256", "-h", "256", "-a", str(src), "-o", str(dst)],
                check=True,
            )
        else:
            dst.write_bytes(src.read_bytes())
        _convert_icon_to_bw(name, dst)
        resolved[name] = str(dst.relative_to(ROOT_DIR))
    return resolved


class FigCraftMCP:
    def __init__(self, cli_path: Path, cwd: Path) -> None:
        self.proc = subprocess.Popen(
            [str(cli_path), "mcp"],
            cwd=str(cwd),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self._id = 0
        self._init()

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def _send(self, payload: dict[str, Any]) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()

    def _recv(self, target_id: int) -> dict[str, Any]:
        assert self.proc.stdout is not None
        while True:
            line = self.proc.stdout.readline()
            if not line:
                err = self.proc.stderr.read() if self.proc.stderr else ""
                raise RuntimeError(f"FigCraft MCP terminated early: {err}")
            msg = json.loads(line)
            if msg.get("id") == target_id:
                return msg

    def _init(self) -> None:
        rid = self._next_id()
        self._send(
            {
                "jsonrpc": "2.0",
                "id": rid,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "vol1-stack-deck", "version": "3.0"},
                },
            }
        )
        resp = self._recv(rid)
        if "error" in resp:
            raise RuntimeError(resp["error"])
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def tool(self, name: str, arguments: dict[str, Any]) -> Any:
        rid = self._next_id()
        self._send(
            {
                "jsonrpc": "2.0",
                "id": rid,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )
        resp = self._recv(rid)
        if "error" in resp:
            raise RuntimeError(f"MCP error ({name}): {resp['error']}")
        result = resp["result"]
        if result.get("isError"):
            text = "\n".join(c.get("text", "") for c in result.get("content", []))
            raise RuntimeError(f"Tool error ({name}): {text}")
        content = result.get("content", [])
        if content and content[0].get("type") == "text":
            txt = content[0]["text"]
            try:
                return json.loads(txt)
            except Exception:
                return txt
        return result

    def run_cmd(self, command: str, params: dict[str, Any]) -> Any:
        return self.tool("run_command", {"command": command, "params": params})

    def create_frame(self, name: str) -> int:
        res = self.run_cmd(
            "node.create",
            {
                "type": "frame",
                "x": 0,
                "y": 0,
                "width": SLIDE_W,
                "height": SLIDE_H,
                "name": name,
                "props": {"fill": BG_WHITE},
                "select": False,
            },
        )
        return int(res["id"])

    def batch(self, commands: list[dict[str, Any]], label: str = "slide") -> None:
        chunk_size = 180
        for i in range(0, len(commands), chunk_size):
            self.tool("batch", {"commands": commands[i : i + chunk_size], "label": label})

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


class StackCanvas:
    def __init__(self, mcp: FigCraftMCP, root_id: int, icons: dict[str, str]) -> None:
        self.mcp = mcp
        self.root = root_id
        self.icons = icons
        self.cmds: list[dict[str, Any]] = []
        self._seq = 0

    def _ref(self) -> str:
        self._seq += 1
        return f"n_{self._seq}"

    def box(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        fill: str = BG_WHITE,
        stroke: str = STROKE_DARK,
        stroke_weight: float = 1.4,
        radius: float = 0,
        dashes: list[float] | None = None,
    ) -> None:
        props: dict[str, Any] = {
            "fill": fill,
            "stroke": stroke,
            "strokeWeight": stroke_weight,
            "cornerRadius": radius,
        }
        if dashes:
            props["dashes"] = dashes
        self.cmds.append(
            {
                "command": "node.create",
                "params": {
                    "type": "rectangle",
                    "x": x,
                    "y": y,
                    "width": w,
                    "height": h,
                    "parent": self.root,
                    "props": props,
                    "select": False,
                },
            }
        )

    def text(
        self,
        x: float,
        y: float,
        content: str,
        size: float = 13.0,
        color: str = TEXT_MAIN,
        weight: int = 500,
        width: float | None = None,
        center: bool = False,
        right: bool = False,
    ) -> None:
        tag = self._ref()
        params: dict[str, Any] = {
            "text": content,
            "x": x,
            "y": y,
            "parent": self.root,
            "props": {
                "fontFamily": FONT_FAMILY,
                "fontSize": size,
                "fontWeight": weight,
                "fill": color,
            },
            "select": False,
        }
        if width is not None:
            params["width"] = width
        self.cmds.append({"as": tag, "command": "text.create", "params": params})
        if center:
            self.cmds.append({"command": "text.alignCenter", "params": {"ids": [{"$ref": tag}]}})
        elif right:
            self.cmds.append({"command": "text.alignRight", "params": {"ids": [{"$ref": tag}]}})

    def icon(
        self,
        x: float,
        y: float,
        size: float,
        icon_name: str,
        dark_bg: bool = False,
    ) -> None:
        # Pure monochrome black icons render directly on pure white canvas (#FFFFFF)
        self.cmds.append(
            {
                "command": "image.place",
                "params": {
                    "path": self.icons[icon_name],
                    "x": x,
                    "y": y,
                    "width": size,
                    "height": size,
                    "parent": self.root,
                    "mode": "fit",
                },
            }
        )

    def slide_title(self, tag: str, title: str, subtitle: str) -> None:
        self.text(48, 22, title, size=21.5, weight=700, color=TEXT_MAIN, width=1340)
        self.text(48, 53, subtitle, size=13.0, weight=400, color=TEXT_SUB, width=1340)
        self.box(1412, 26, 140, 28, fill=BG_WHITE, stroke=STROKE_DARK, stroke_weight=1.4, radius=0)
        self.text(1416, 32.5, tag, size=12.0, weight=700, color=TEXT_MAIN, width=132, center=True)
        self.box(48, 84, 1504, 1.5, fill=STROKE_DARK, stroke=STROKE_DARK, stroke_weight=0, radius=0)

    def layer_tag(self, y: float, h: float, label: str, accent: str = STROKE_DARK) -> None:
        self.box(48, y, 76, h, fill=BG_WHITE, stroke=STROKE_DARK, stroke_weight=1.2, radius=0)
        lines = label.count("\n") + 1
        text_h = lines * 16.5
        self.text(50, y + (h - text_h) / 2, label, size=11.8, weight=700, color=TEXT_MAIN, width=72, center=True)

    def bar(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        title: str,
        icon_name: str,
        fill: str = BG_WHITE,
        stroke: str = STROKE_DARK,
        sub: str = "",
        icon_size: float = 26,
        title_size: float = 14.5,
        sub_size: float = 11.8,
        dark_icon: bool = False,
        stroke_weight: float = 1.4,
    ) -> None:
        """Crisp white architectural layer bar with black border and official OSS icon."""
        self.box(x, y, w, h, fill=fill, stroke=stroke, stroke_weight=stroke_weight, radius=0)
        approx_title_w = len(title) * (title_size * 0.64)
        sub_lines = sub.split("\n") if sub else []
        approx_sub_w = max((len(line) * (sub_size * 0.56) for line in sub_lines), default=0)
        text_w = max(approx_title_w, approx_sub_w)
        total_w = icon_size + 10 + text_w
        if total_w > w - 24:
            ix = x + 10
            tx = ix + icon_size + 8
            tw = w - (tx - x) - 8
        else:
            ix = x + (w - total_w) / 2
            tx = ix + icon_size + 10
            tw = text_w + 20

        self.icon(ix, y + (h - icon_size) / 2, icon_size, icon_name, dark_bg=dark_icon)
        if sub_lines:
            sub_h = len(sub_lines) * (sub_size + 3)
            block_h = 20 + sub_h
            ty = y + (h - block_h) / 2
            self.text(tx, ty, title, size=title_size, weight=700, color=TEXT_MAIN, width=tw)
            self.text(tx, ty + 19, sub, size=sub_size, weight=400, color=TEXT_SUB, width=tw)
        else:
            self.text(tx, y + (h - 18) / 2, title, size=title_size, weight=700, color=TEXT_MAIN, width=tw)

    def block_card(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        title: str,
        sub: str,
        icon_name: str,
        fill: str = BG_WHITE,
        stroke: str = STROKE_DARK,
        icon_size: float = 28,
        title_size: float = 13.0,
        sub_size: float = 11.2,
        dark_icon: bool = False,
        left_accent: str | None = None,
        dashes: list[float] | None = None,
    ) -> None:
        self.box(x, y, w, h, fill=fill, stroke=stroke, stroke_weight=1.3, radius=0, dashes=dashes)
        ix = x + 10
        iy = y + (h - icon_size) / 2 if ("\n" not in sub and h <= 70) else y + 12
        self.icon(ix, iy, icon_size, icon_name, dark_bg=dark_icon)
        tx = ix + icon_size + 10
        tw = w - (tx - x) - 8
        if "\n" not in sub and h <= 64:
            self.text(tx, y + (h - 34) / 2, title, size=title_size, weight=700, color=TEXT_MAIN, width=tw)
            self.text(tx, y + (h - 34) / 2 + 19, sub, size=sub_size, weight=400, color=TEXT_SUB, width=tw)
        else:
            self.text(tx, y + 10, title, size=title_size, weight=700, color=TEXT_MAIN, width=tw)
            self.text(tx, y + 30, sub, size=sub_size, weight=400, color=TEXT_SUB, width=tw)

    def arrow(
        self,
        points: list[tuple[float, float]],
        color: str = STROKE_DARK,
        weight: float = 1.8,
        dashed: bool = False,
        label: str = "",
        label_pos: tuple[float, float] | None = None,
    ) -> None:
        for idx in range(len(points) - 1):
            x1, y1 = points[idx]
            x2, y2 = points[idx + 1]
            props: dict[str, Any] = {"stroke": color, "strokeWeight": weight, "strokeCap": "round", "strokeJoin": "round"}
            if dashed:
                props["dashes"] = [5, 4]
            self.cmds.append(
                {
                    "command": "node.create",
                    "params": {
                        "type": "vector",
                        "x": min(x1, x2),
                        "y": min(y1, y2),
                        "points": [[x1 - min(x1, x2), y1 - min(y1, y2)], [x2 - min(x1, x2), y2 - min(y1, y2)]],
                        "closed": False,
                        "parent": self.root,
                        "props": props,
                        "select": False,
                    },
                }
            )
        ex, ey = points[-1]
        px, py = points[-2]
        dx, dy = ex - px, ey - py
        length = (dx * dx + dy * dy) ** 0.5 or 1.0
        ux, uy = dx / length, dy / length
        nx, ny = -uy, ux
        sz, half = 7.5, 4.2
        p1 = [ex, ey]
        p2 = [ex - ux * sz + nx * half, ey - uy * sz + ny * half]
        p3 = [ex - ux * sz - nx * half, ey - uy * sz - ny * half]
        minx = min(p1[0], p2[0], p3[0])
        miny = min(p1[1], p2[1], p3[1])
        self.cmds.append(
            {
                "command": "node.create",
                "params": {
                    "type": "vector",
                    "x": minx,
                    "y": miny,
                    "points": [[p[0] - minx, p[1] - miny] for p in (p1, p2, p3)],
                    "closed": True,
                    "parent": self.root,
                    "props": {"fill": color, "stroke": color, "strokeWeight": 0.5},
                    "select": False,
                },
            }
        )
        if label:
            lx, ly = label_pos if label_pos else ((points[0][0] + points[-1][0]) / 2, (points[0][1] + points[-1][1]) / 2)
            lw = max(78, len(label) * 7.2 + 16)
            self.box(lx - lw / 2, ly - 10, lw, 20, fill=BG_WHITE, stroke=color, stroke_weight=1.1, radius=0)
            self.text(lx - lw / 2 + 2, ly - 6.5, label, size=10.8, weight=700, color=color, width=lw - 4, center=True)

    def footer(self, note: str) -> None:
        self.box(48, 846, 1504, 34, fill=BG_WHITE, stroke=STROKE_DARK, stroke_weight=1.1, radius=0)
        self.text(62, 855, note, size=11.5, weight=500, color=TEXT_SUB, width=1476)

    def role_card(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        title: str,
        where: str,
        body: str,
        icon_name: str,
        title_size: float = 12.4,
        body_size: float = 11.0,
        icon_size: float = 26,
    ) -> None:
        """Pure B&W academic catalog card explaining a tech stack's exact role, reason, and file/VM location."""
        self.box(x, y, w, h, fill=BG_WHITE, stroke=STROKE_DARK, stroke_weight=1.3, radius=0)
        self.icon(x + 10, y + 7, icon_size, icon_name)
        tag_w = max(84, min(116, len(where) * 7.2 + 14))
        self.box(x + w - tag_w - 10, y + 8, tag_w, 22, fill=BG_WHITE, stroke=STROKE_DARK, stroke_weight=1.0, radius=0)
        self.text(x + w - tag_w - 8, y + 12, where, size=9.8, weight=700, color=TEXT_MAIN, width=tag_w - 4, center=True)
        tx = x + icon_size + 18
        tw = w - (tx - x) - tag_w - 16
        self.text(tx, y + 11, title, size=title_size, weight=700, color=TEXT_MAIN, width=tw)
        self.box(x + 10, y + 39, w - 20, 1.0, fill=STROKE_DARK, stroke=STROKE_DARK, stroke_weight=0, radius=0)
        self.text(x + 12, y + 48, body, size=body_size, weight=400, color=TEXT_MAIN, width=w - 24)

    def flush(self, label: str) -> None:
        if self.cmds:
            self.mcp.batch(self.cmds, label=label)
            self.cmds = []


# ===========================================================================
# SLIDE 1: Full Bottom-Up Stack Overview (Academic Paper B&W Style + OSS Icons)
# ===========================================================================
def build_slide_01(mcp: FigCraftMCP, icons: dict[str, str]) -> int:
    mcp.run_cmd("page.rename", {"name": "01-Full-Stack-Overview"})
    fid = mcp.create_frame("slide-01-full-stack-architecture")
    d = StackCanvas(mcp, fid, icons)

    d.slide_title(
        "Fig. 1 / 6",
        "Fig. 1 — vol1_Infra (Prod-in-a-Mac) Bottom-Up 전체 아키텍처 스택 (L0 → L6)",
        "물리 하드웨어(L0) 위에 Tart 하이퍼바이저(L1), 7개 VM(L2), 런타임(L3), 관리 평면·K8s·워크로드(L4~L6)가 수직 적층되는 전체 구조",
    )

    # Aligned column geometry (total w = 1416 from x=136..1552):
    # Col 1 (macprod-ops): x=136, w=310
    # Col 2 (macprod-cp-1..3): x=460, w=456 -> 3 VMs of w=146 (gap=9)
    # Col 3 (macprod-wk-1..3): x=930, w=622 -> 3 VMs of w=200 (gap=11)

    # ---------------- L0: Physical Hardware (y=778, h=54) ----------------
    d.layer_tag(778, 54, "L0 · HW")
    d.bar(
        136, 778, 1416, 54,
        "Apple M4 Max · ARM64 16 Core · 128 GB RAM · 969 Gi SSD (macOS 15.7.4)",
        "apple", sub="전체 VM 할당: 17 vCPU · 48 GB RAM · 260 GB Sparse (호스트 ~80 GB 여유 · Swap 0)",
        icon_size=26, title_size=14.2, sub_size=11.4,
    )

    # ---------------- L1: Hypervisor (y=716, h=54) ----------------
    d.layer_tag(716, 54, "L1 · HV")
    d.bar(
        136, 716, 1416, 54,
        "Cirrus Labs Tart v2.31.0  (Hypervisor: Apple Virtualization.framework / HVF)",
        "tart", sub="tart run --no-graphics --net-softnet-allow=0.0.0.0/0 · vmnet Softnet 192.168.67.0/24",
        icon_size=26, title_size=14.2, sub_size=11.4,
    )

    # ---------------- L2: 7 VMs sitting on Tart (y=634, h=74) ----------------
    d.layer_tag(634, 74, "L2 · VM")
    d.bar(
        136, 634, 310, 74,
        "VM: macprod-ops",
        "docker", sub="Ubuntu 24.04 · 2C / 6G / 35G\nExternal Mgmt (Non-K8s)",
        icon_size=26, title_size=13.2, sub_size=10.8,
    )
    for i in range(3):
        cx = 460 + i * 155
        tag = "Bootstrap" if i == 0 else ("Demo 1" if i == 1 else "Quorum")
        d.bar(
            cx, 634, 146, 74,
            f"cp-{i+1}",
            "kubernetes", sub=f"2C/4G/30G\n({tag})",
            icon_size=20, title_size=12.6, sub_size=10.4,
        )
    for i in range(3):
        wx = 930 + i * 211
        d.bar(
            wx, 634, 200, 74,
            f"macprod-wk-{i+1}",
            "kubernetes", sub="Ubuntu 24.04 · ARM64\n3C / 10G / 45G Sparse",
            icon_size=22, title_size=12.6, sub_size=10.4,
        )

    # ---------------- L3: Host OS Runtime Layer (y=566, h=60) ----------------
    d.layer_tag(566, 60, "L3 · OS")
    d.bar(
        136, 566, 310, 60,
        "Docker Compose + systemd",
        "docker", sub="k6 v2.4.0 CLI · SSH CA (10-sshd)",
        icon_size=24, title_size=12.6, sub_size=10.8,
    )
    d.bar(
        460, 566, 1092, 60,
        "containerd 2.2.1 (Zot certs.d) + kubelet / kubeadm v1.32.13",
        "docker", sub="overlay · br_netfilter · Swap 0 · /opt/local-path-provisioner (wk) · TrustedUserCAKeys",
        icon_size=26, title_size=13.8, sub_size=11.4,
    )

    # ---------------- L4~L6 Stacked vertically per VM Group (y=102..558) ----------------
    d.layer_tag(416, 142, "L4 · Core")
    d.layer_tag(186, 220, "L5 · Plat")
    d.layer_tag(102, 74, "L6 · App")

    # Left Column (x=136, w=310): macprod-ops External Management Plane (Bottom=L4 LB -> Mid=Backing Services -> Top=L6 Load Client)
    d.box(136, 102, 310, 456, fill=BG_WHITE, stroke=STROKE_DARK, stroke_weight=1.4, radius=0, dashes=[5, 3])
    d.text(146, 112, "클라우드 외부 관리 평면 (macprod-ops)", size=12.8, weight=700, color=TEXT_MAIN, width=290, center=True)
    ops_stack = [
        ("Grafana k6 v2.4.0", "Bastion 부하 (30 VU · 3,067 req)", "k6", False),
        ("HashiCorp Vault 1.18.3", ":8200 KV v2 · K8s Auth · SSH CA", "vault", True),
        ("Gitea 1.22 (GitOps SCM)", ":3000 gitops · order-service 저장소", "gitea", False),
        ("CNCF Zot v2.1.2 + Trivy", ":5000 OCI 레지스트리 · CVE Gate", "trivy", False),
        ("SeaweedFS 4.55 S3", ":8333 S3 (4 버킷) · :8888 Filer 캐시", "seaweedfs", False),
        ("HAProxy 3.0-alpine", ":6443 API LB · :80 Ingress · :8404", "haproxy", False),
    ]
    oy = 142
    for t, s, ic, dk in ops_stack:
        d.block_card(146, oy, 290, 62, t, s, ic, fill=BG_WHITE, stroke=STROKE_DARK, icon_size=26, title_size=12.2, sub_size=10.5, dark_icon=dk)
        oy += 68

    # Center Column (x=460, w=456): L4 Control Plane -> L5 IaC Definitions -> L6 Makefile CLI
    d.bar(
        460, 490, 456, 68,
        "Stacked etcd v3 (3-Node Quorum)",
        "kubernetes", sub="cp-2 장애 시 2/3 쿼럼 유지 · etcd-s3-backup (02:15)",
        icon_size=26, title_size=13.0, sub_size=11.0,
    )
    d.bar(
        460, 416, 456, 68,
        "kube-apiserver · controller · scheduler",
        "kubernetes", sub="api.macprod.internal:6443 (HAProxy L4 LB)",
        icon_size=26, title_size=13.0, sub_size=11.0,
    )
    d.box(460, 186, 456, 220, fill=BG_WHITE, stroke=STROKE_DARK, stroke_weight=1.3, radius=0, dashes=[5, 3])
    d.text(472, 194, "IaC 정의 파일 소스 (Mac Host → Cluster)", size=12.6, weight=700, color=TEXT_MAIN, width=432, center=True)
    d.block_card(474, 220, 428, 56, "cluster.yaml (SSOT)", "7-VM CPU/RAM/Disk · K8s/Helm 버전 원본", "apple", icon_size=24)
    d.block_card(474, 282, 428, 56, "Terraform v1.5.7 (2-Layer)", "local-m4 (VM/SSH) + platform-state (S3/Vault/SSH CA)", "terraform", icon_size=24)
    d.block_card(474, 344, 428, 56, "Ansible 2.18.14 (Playbook 01~05)", "OS · ops-stack · kubeadm HA · reconcile · ssh-ca", "ansible", icon_size=24)

    d.bar(
        460, 102, 456, 74,
        "Makefile & CLI (ops-vm-ctl.sh)",
        "kubernetes", sub="make doctor / up / status / ssh-cert / ssh / demo-*",
        icon_size=26, title_size=13.2, sub_size=11.0,
    )

    # Right Column (x=930, w=622): L4 CNI+Gateway -> L5 4 Platform Pillars -> L6 Demo App
    d.bar(
        930, 490, 622, 68,
        "Cilium 1.20.5 eBPF + local-path + cert-manager",
        "cilium", sub="kube-proxy 대체 · 10.244.0.0/16 · Default SC (v0.0.31) · TLS 발급",
        icon_size=26, title_size=13.2, sub_size=10.8,
    )
    d.bar(
        930, 416, 622, 68,
        "Gateway API v1.6.3 (Envoy :30080) + CoreDNS + HTTPRoute CRDs",
        "envoy", sub="*.macprod.internal (order/argocd/grafana/hubble) · ClusterSecretStore · ValidatingPolicy",
        icon_size=26, title_size=13.0, sub_size=10.6,
    )
    cols = [
        ("GitOps / CD", [("ArgoCD 10.18", "14 Apps Sync", "cncf-argo", False), ("Rollouts 2.4", "Canary + S3", "helm", False)]),
        ("SecOps", [("ESO 2.15.0", "Vault 30s Sync", "external-secrets", False), ("Kyverno 3.10", "CEL Policy", "kyverno", False)]),
        ("State / DR", [("CNPG PG 16", "x3 + Barman", "postgresql", False), ("Velero 12.2", "Kopia S3 DR", "velero", False)]),
        ("Observability", [("Prom / Graf", "15s + UI :80", "prometheus", False), ("Loki / Tempo", "Log + OTel", "opentelemetry", False)]),
    ]
    cw = 148
    for idx, (ctitle, items) in enumerate(cols):
        cx = 930 + idx * (cw + 10)
        d.box(cx, 186, cw, 220, fill=BG_WHITE, stroke=STROKE_DARK, stroke_weight=1.3, radius=0, dashes=[5, 3])
        d.text(cx + 4, 194, ctitle, size=12.2, weight=700, color=TEXT_MAIN, width=cw - 8, center=True)
        iy = 220
        for it, isub, iic, idk in items:
            d.block_card(cx + 6, iy, cw - 12, 86, it, isub, iic, icon_size=22, title_size=11.3, sub_size=10.0, dark_icon=idk)
            iy += 94

    d.bar(
        930, 102, 622, 74,
        "Demo Workload: order-service v1.0.0 (FastAPI ARM64 x 3)",
        "fastapi", sub="topologySpreadConstraints (wk-1, wk-2, wk-3 각 1대) · http://order.macprod.internal",
        icon_size=28, title_size=13.8, sub_size=11.0,
    )

    d.footer(
        "읽는 순서 (Bottom-Up): L0 Apple M4 Max → L1 Tart Hypervisor → L2 7개 VM → L3 OS/Runtime → L4~L6 Ops 관리 평면 · K8s 컨트롤 플레인 · 워커 플랫폼/앱 적층 구조"
    )
    d.flush("slide-01")
    return fid


# ===========================================================================
# SLIDE 2: Layer Split Zoom A — L0~L4 (IaC, macprod-ops & macprod-cp-1..3)
# ===========================================================================
def build_slide_02(mcp: FigCraftMCP, icons: dict[str, str]) -> int:
    pid = mcp.run_cmd("page.add", {})["id"]
    mcp.run_cmd("page.select", {"id": pid})
    mcp.run_cmd("page.rename", {"name": "02-Infra-Ops-CP-Layer"})
    fid = mcp.create_frame("slide-02-l0-l4-ops-cp-iac-stack")
    d = StackCanvas(mcp, fid, icons)

    d.slide_title(
        "Fig. 2 / 6",
        "Fig. 2 — 계층 분할 [하부] L0~L4 하드웨어 · Tart · macprod-ops · macprod-cp-1..3 & 정의 위치",
        "물리 머신과 Tart 하이퍼바이저 위에 외부 관리 평면(macprod-ops)과 3-Master HA 컨트롤 플레인(cp-1..3)이 어떻게 정의·배치되는지 상세 표시",
    )

    # Bottom Full-width Hardware & Hypervisor (x=136, w=1416)
    d.layer_tag(778, 54, "L0 · HW")
    d.bar(
        136, 778, 1416, 54,
        "Apple M4 Max · ARM64 16 Core · 128 GB RAM · 969 Gi NVMe SSD (macOS 15.7.4)",
        "apple", sub="할당 총계: 17 vCPU / 48 GB RAM (Swap 0) · 호스트 약 80 GB 여유",
        icon_size=26, title_size=14.0, sub_size=11.5,
    )

    d.layer_tag(716, 54, "L1 · HV")
    d.bar(
        136, 716, 1416, 54,
        "Cirrus Labs Tart v2.31.0  (Apple Virtualization.framework / HVF · vmnet Softnet)",
        "tart", sub="tart run --no-graphics --net-softnet-allow=0.0.0.0/0 · 비DHCP VIP 차단 제약",
        icon_size=26, title_size=14.0, sub_size=11.5,
    )

    # Col A (IaC Source): x=136, w=320 | Col B (ops): x=472, w=532 | Col C (cp-1..3): x=1020, w=532
    d.layer_tag(636, 72, "L2 · VM")
    d.bar(136, 636, 320, 72, "SSOT & 프로비저닝", "terraform", sub="macprod-* 7대만 격리 생성", icon_size=26, title_size=13.2, sub_size=11.2)
    d.bar(472, 636, 532, 72, "VM: macprod-ops (2C · 6 GB · 35 GB)", "docker", sub="Ubuntu 24.04.4 ARM64 · K8s 비가입 · cluster.yaml#L41-45", icon_size=28, title_size=13.5, sub_size=11.2)
    for i in range(3):
        cx = 1020 + i * 180
        role = "Bootstrap" if i == 0 else ("Demo 1 Target" if i == 1 else "Quorum #3")
        d.bar(cx, 636, 172, 72, f"macprod-cp-{i+1}", "kubernetes", sub=f"2C / 4G / 30G\n({role})", icon_size=22, title_size=12.4, sub_size=10.4)

    d.layer_tag(568, 60, "L3 · OS")
    d.bar(136, 568, 320, 60, "Ansible 01-prepare · common", "ansible", sub="hosts · Swap 0 · chrony · SSH CA", icon_size=24, title_size=12.4, sub_size=10.8)
    d.bar(472, 568, 532, 60, "Docker Compose + macprod-ops-bootstrap.service", "docker", sub="0바이트 .sdx 자가치유 → docker compose up → Vault Auto-Unseal", icon_size=24, title_size=12.8, sub_size=10.8)
    d.bar(1020, 568, 532, 60, "containerd 2.2.1 + kubelet / kubeadm v1.32.13 (roles/k8s-node)", "docker", sub="overlay/br_netfilter · Zot certs.d · --node-ip · SSH CA 10-macprod", icon_size=24, title_size=12.6, sub_size=10.8)

    d.layer_tag(104, 456, "L3~L4\n스택")

    # Col A Detailed IaC Mapping (y=104..560)
    d.box(136, 104, 320, 456, fill=BG_WHITE, stroke=STROKE_DARK, stroke_weight=1.4, radius=0, dashes=[5, 3])
    d.text(146, 114, "어디에 정의되어 있는가? (IaC 맵)", size=13.0, weight=700, color=TEXT_MAIN, width=300, center=True)
    iac_items = [
        ("cluster.yaml (SSOT)", "VM 이름/vCPU/RAM/Disk\nK8s·Helm·이미지 버전 원본", "apple"),
        ("terraform/local-m4/main.tf", "tart clone · tart set 실행\n~/.ssh/macprod_ed25519 생성", "terraform"),
        ("terraform/platform-state", "SeaweedFS S3 State 백엔드\nVault KV·K8s Auth·SSH CA 생성", "vault"),
        ("ansible/roles/ops-stack", "haproxy.cfg · docker-compose\nbootstrap-ops.sh 템플릿 정의", "ansible"),
        ("ansible/03-k8s & 04-reconcile", "kubeadm HA init/join\n재부팅 IP/SAN/CoreDNS 복구", "kubernetes"),
    ]
    iy = 148
    for t, s, ic in iac_items:
        d.block_card(146, iy, 300, 74, t, s, ic, icon_size=26, title_size=12.2, sub_size=10.6, dark_icon=(ic == "vault"))
        iy += 81

    # Col B Detailed macprod-ops Stack (y=104..560)
    d.box(472, 104, 532, 456, fill=BG_WHITE, stroke=STROKE_DARK, stroke_weight=1.4, radius=0, dashes=[5, 3])
    d.text(484, 114, "macprod-ops 상주 6종 스택 (외부 관리 평면)", size=13.2, weight=700, color=TEXT_MAIN, width=508, center=True)
    ops_detail = [
        ("1. HAProxy 3.0-alpine", ":6443 API L4 LB (cp-1..3) · :80 Ingress LB (wk-1..3:30080) · :8404 Stats", "haproxy", False),
        ("2. SeaweedFS 4.55 S3 + Filer", ":8333 S3 (terraform-state, cnpg, velero, loki) · :8888 Filer 플러그인 캐시", "seaweedfs", False),
        ("3. CNCF Zot v2.1.2 + Trivy", ":5000 ARM64 OCI 레지스트리 · 푸시 전 CVE(HIGH/CRIT) 스캔 게이트", "trivy", False),
        ("4. Gitea 1.22 (GitOps SCM)", ":3000 HTTP · :2222 SSH · macprod/gitops & order-service 저장소", "gitea", False),
        ("5. HashiCorp Vault 1.18.3", ":8200 File Backend · KV v2 (ESO) · SSH CA (ssh-client-signer, 1~8h)", "vault", True),
        ("6. Grafana k6 v2.4.0 CLI", "클러스터 외부 부하 생성 → HAProxy :80 종단 측정 (30 VU · p95 226ms)", "k6", False),
    ]
    oy = 144
    for t, s, ic, dk in ops_detail:
        d.block_card(484, oy, 508, 61, t, s, ic, icon_size=28, title_size=12.6, sub_size=10.7, dark_icon=dk)
        oy += 68

    # Col C Detailed cp-1..3 HA Control Plane (y=104..560)
    d.box(1020, 104, 532, 456, fill=BG_WHITE, stroke=STROKE_DARK, stroke_weight=1.4, radius=0, dashes=[5, 3])
    d.text(1032, 114, "macprod-cp-1..3 HA 컨트롤 플레인 계층", size=13.2, weight=700, color=TEXT_MAIN, width=508, center=True)
    d.block_card(1032, 148, 508, 86, "Static Control Plane Pods (전 CP 3대 동일 실행)", "kube-apiserver · kube-controller-manager · kube-scheduler\nStacked etcd v3 (3-Node Raft Quorum, 1대 장애 시 2/3 쿼럼 유지)", "kubernetes", icon_size=28, title_size=12.8, sub_size=11.0)
    d.block_card(1032, 246, 508, 92, "노드별 역할 구분 (cluster.yaml & 03-k8s-cluster.yml)", "cp-1 (bootstrap: true): kubeadm init · join 토큰 · 초기 & Demo 1 etcd 백업\ncp-2 (bootstrap: false): Demo 1 (tart stop) 장애 주입 대상\ncp-3 (bootstrap: false): cp-2 정지 중 cp-1과 함께 쓰기 쿼럼 유지", "kubernetes", icon_size=28, title_size=12.8, sub_size=10.8)
    d.block_card(1032, 350, 508, 92, "etcd S3 백업 & 공통 DaemonSets", "전 3대 CP: /usr/local/bin/etcd-s3-backup.sh (매일 02:15 cron → SeaweedFS)\n공통 DaemonSet: Cilium eBPF · Promtail · Node Exporter (Envoy 미실행)", "seaweedfs", icon_size=28, title_size=12.8, sub_size=10.8)
    d.block_card(1032, 454, 508, 94, "API L4 HA 연결 (HAProxy ↔ kubeadm certSANs)", "macprod-ops HAProxy :6443 → cp-1..3:6443 헬스체크(1s inter, 2 fall)\nSAN에 ops_ip, api.macprod.internal, cp-1..3 IP 포함 → 04-reconcile 갱신", "haproxy", icon_size=28, title_size=12.8, sub_size=10.8)

    d.footer(
        "정의 위치 요약: VM 스펙=infra/config/cluster.yaml | Ops 스택=infra/ansible/roles/ops-stack/ | K8s HA=infra/ansible/playbooks/03-k8s-cluster.yml | SSH CA=infra/terraform/platform-state/"
    )
    d.flush("slide-02")
    return fid


# ===========================================================================
# SLIDE 3: Layer Split Zoom B — L5~L6 (Network, Gateway & Workers Workload Stack)
# ===========================================================================
def build_slide_03(mcp: FigCraftMCP, icons: dict[str, str]) -> int:
    pid = mcp.run_cmd("page.add", {})["id"]
    mcp.run_cmd("page.select", {"id": pid})
    mcp.run_cmd("page.rename", {"name": "03-Network-Workers-Layer"})
    fid = mcp.create_frame("slide-03-l5-l6-network-workers")
    d = StackCanvas(mcp, fid, icons)

    d.slide_title(
        "Fig. 3 / 6",
        "Fig. 3 — 계층 분할 [상부] L4~L6 Cilium 네트워크 · 플랫폼 4대 스택 · order-service 적층",
        "3대 워커 VM (총 9 vCPU · 30 GB RAM · 135 GB) 위에 eBPF 네트워크 경계(L4), 4대 플랫폼 계층(L5), order-service 앱(L6)이 쌓이는 구조",
    )

    # Bottom Base Stack (x=136, w=1416)
    d.layer_tag(782, 50, "L0~L1")
    d.bar(136, 782, 1416, 50, "Apple M4 Max (16C / 128 GB)  →  Tart v2.31.0 Hypervisor (vmnet Softnet 192.168.67.0/24)", "tart", icon_size=26, title_size=13.8)

    # L2 Workers (x=136, w=1416 -> 3 workers of w=460, gap=18)
    d.layer_tag(714, 60, "L2 · VM")
    for i in range(3):
        wx = 136 + i * 478
        d.bar(wx, 714, 460, 60, f"macprod-wk-{i+1} (Worker #{i+1})", "kubernetes", sub="Ubuntu 24.04 · 3 vCPU · 10 GB RAM · 45 GB Sparse", icon_size=24, title_size=13.5, sub_size=11.0)

    # L3 Runtime (y=650, h=56)
    d.layer_tag(650, 56, "L3 · OS")
    d.bar(136, 650, 1416, 56, "containerd 2.2.1 (Zot :5000 certs.d) · kubelet v1.32.13 (node-role: worker=true) · /opt/local-path-provisioner", "docker", icon_size=24, title_size=13.5)

    # L4 Network & Ingress Layer (y=560, h=82)
    d.layer_tag(560, 82, "L4 · Net")
    d.block_card(136, 560, 460, 82, "Cilium 1.20.5 eBPF + Hubble UI", "kubeProxyReplacement=true · Pod CIDR 10.244.0.0/16\ninstall-core.sh#L41-72", "cilium", icon_size=28)
    d.block_card(614, 560, 460, 82, "Gateway API v1.6.3 + Envoy (:30080)", "hostNetwork :30080 (worker=true 3대 바인딩)\ncilium-gateway.yaml · gateway-routes.yaml", "envoy", icon_size=28)
    d.block_card(1092, 560, 460, 82, "CoreDNS + cert-manager + local-path", "*.macprod.internal → live ops_ip 동적 패치\ncerts (v1.21.3) · Default StorageClass (v0.0.31)", "kubernetes", icon_size=28)

    # L5 Platform 4 Columns (y=198..548, h=350)
    d.layer_tag(198, 350, "L5 · Plat")
    plat_cols = [
        (
            "GitOps & CD (Wave 0~4)",
            [
                ("ArgoCD 10.18.2 (v3.6.2)", "macprod-root App-of-Apps\n14개 App Synced/Healthy\ngitops/root-app.yaml", "cncf-argo", False),
                ("Argo Rollouts 2.43.12", "gatewayAPI 플러그인 :8888 캐시\n카나리 25%→60% 자동 롤백\ninstall-core.sh#L141-156", "helm", False),
            ],
        ),
        (
            "Security & Zero-Trust",
            [
                ("External Secrets 2.15.0", "ClusterSecretStore (vault-backend)\n30s/1m 시크릿 동기화\napps/02-external-secrets.yaml", "external-secrets", False),
                ("Kyverno 3.10.0 + SSH CA", "v1.20 CEL (:latest/PrivEsc 차단)\n7 VM PasswordAuth 차단\nkyverno-policies.yaml", "kyverno", False),
            ],
        ),
        (
            "Stateful DB & DR",
            [
                ("CloudNativePG 0.29.2", "order-db PG 16.6 x 3 HA\n각 3Gi local-path + Barman S3\ncnpg-cluster/order-db.yaml", "postgresql", False),
                ("Velero 12.2.5 (Kopia)", "velero-backups S3 버킷 연동\n워커 DaemonSet PVC 복구\napps/07-velero.yaml", "velero", False),
            ],
        ),
        (
            "Observability (LGTM+OTel)",
            [
                ("Prometheus + Grafana", "kps 93.9 (1536Mi / 15s 스크랩)\nAlertmanager + 통합 UI\napps/08-kube-prometheus-stack", "prometheus", False),
                ("Loki · Promtail · Tempo · OTel", "Loki 512Mi+5G · Tempo 1536Mi+5G\nOTel 0.182 (:4317/4318) 트레이스\napps/09~12-*.yaml", "opentelemetry", False),
            ],
        ),
    ]
    cw = 342
    for idx, (pt, cards) in enumerate(plat_cols):
        px = 136 + idx * (cw + 16)
        d.box(px, 198, cw, 350, fill=BG_WHITE, stroke=STROKE_DARK, stroke_weight=1.3, radius=0, dashes=[5, 3])
        d.text(px + 6, 208, pt, size=13.0, weight=700, color=TEXT_MAIN, width=cw - 12, center=True)
        cy = 240
        for ct, cs, cic, cdk in cards:
            d.block_card(px + 10, cy, cw - 20, 144, ct, cs, cic, icon_size=28, title_size=12.4, sub_size=10.8, dark_icon=cdk)
            cy += 154

    # L6 Top App Layer (y=102, h=86)
    d.layer_tag(102, 86, "L6 · App")
    d.bar(
        136, 102, 1416, 86,
        "Demo Workload: order-service v1.0.0 (FastAPI ARM64 x 3 · Zot :5000) — http://order.macprod.internal",
        "fastapi",
        sub="wk-1 · wk-2 · wk-3 각 1파드 균등 분산 (maxSkew: 1) · Envoy :30080 라우팅 · CNPG order-db-rw 연결 · /metrics & OTel 트레이스 발행\n정의: apps/order-service/k8s/base/rollout.yaml · overlays/local-m4 · overlays/cloud-eks (AWS EKS Parity)",
        icon_size=30, title_size=14.0, sub_size=11.0,
    )

    d.footer(
        "배치 요약: order-service(3) · order-db(3) · Cilium Envoy · Velero node-agent는 워커 3대 균등 분산 | Prometheus · Loki(5Gi) · Tempo(5Gi)는 local-path PVC 노드에 영속 고정"
    )
    d.flush("slide-03")
    return fid


# ===========================================================================
# SLIDE 4: Daily Lifecycle & 6 Verified Handover Demos
# ===========================================================================
def build_slide_04(mcp: FigCraftMCP, icons: dict[str, str]) -> int:
    pid = mcp.run_cmd("page.add", {})["id"]
    mcp.run_cmd("page.select", {"id": pid})
    mcp.run_cmd("page.rename", {"name": "04-Ops-And-6-Demos"})
    fid = mcp.create_frame("slide-04-ops-lifecycle-and-demos")
    d = StackCanvas(mcp, fid, icons)

    d.slide_title(
        "Fig. 4 / 6",
        "Fig. 4 — 인수인계 운영 라이프사이클 & 6대 자동 검증 시나리오",
        "Makefile 단일 진입점으로 사전 점검 → 구축 → 단기 SSH CA 접속 → 종료/재부팅 복구 → 6대 실전 장애·보안·DR 데모 실행",
    )

    # Top Horizontal Loop (y=108..236)
    d.layer_tag(108, 128, "운영 루프")
    d.box(136, 108, 1416, 128, fill=BG_WHITE, stroke=STROKE_DARK, stroke_weight=1.3, radius=0, dashes=[5, 3])
    d.text(150, 118, "일상 운영 표준 절차 (Makefile)", size=13.5, weight=700, color=TEXT_MAIN, width=1388)
    ops_steps = [
        ("1. make doctor", "M4 CPU/RAM 128G\n필수 CLI 10종 점검", "apple", False),
        ("2. make up", "tf-vms → ops → k8s\n→ bootstrap → platform", "terraform", False),
        ("3. make status", "7 VM · 6 Nodes · 85 Pods\nArgoCD 14 Apps 점검", "kubernetes", False),
        ("4. make ssh VM=...", "Vault SSH CA 1h 발급\n무패스워드 VM 접속", "vault", True),
        ("5. make stop / reconcile", "WK/CP 정지 → ops Flush\n재부팅 시 자동 복구", "ansible", False),
    ]
    sx = 150
    sw = 258
    for idx, (st, ss, sic, sdk) in enumerate(ops_steps):
        d.block_card(sx, 148, sw, 74, st, ss, sic, icon_size=26, title_size=12.4, sub_size=10.8, dark_icon=sdk)
        if idx < len(ops_steps) - 1:
            d.arrow([(sx + sw, 185), (sx + sw + 24, 185)], color=STROKE_DARK, weight=1.8)
        sx += sw + 24

    # Bottom 3x2 Clean Stack Boxes for 6 Demos (y=258..828)
    d.layer_tag(258, 570, "6대 데모")
    d.box(136, 258, 1416, 570, fill=BG_WHITE, stroke=STROKE_DARK, stroke_weight=1.3, radius=0)
    d.text(150, 268, "실측 검증된 6대 데모 시나리오 (scripts/demos/demo-01~06 · 실행 후 자동 원복)", size=14.0, weight=700, color=TEXT_MAIN, width=1388)

    demos = [
        ("Demo 1 · 3-Master HA & etcd S3", "make demo-ha", "cp-2 강제 정지(tart stop) → HAProxy 2초 우회\n/healthz 40회 중 38 OK · 2/3 etcd 쿼럼 유지\ncp-1에서 62MB etcd 스냅샷 SeaweedFS 업로드", "kubernetes", False),
        ("Demo 2 · 카나리 & Prom 자동 롤백", "make demo-canary", "Gitea에 5xx=75% v2.0.0-bad 커밋 푸시\nEnvoy 25% 분할 → min per-pod non-5xx < 90%\n즉시 RolloutAborted + 100/0 원복 + Revert", "cncf-argo", False),
        ("Demo 3 · PG HA Failover & 백업", "make demo-db", "CNPG Primary order-db-1 강제 삭제\nStandby(order-db-2) 자동 승격 RTO 24s\n센티넬 데이터 무손실 · Barman S3 백업 완료", "postgresql", False),
        ("Demo 4 · Vault ESO & Kyverno CEL", "make demo-security", "Vault secret/apps API_KEY 회전 (v1 → v2)\nESO force-sync 즉시 반영 확인 후 원복\nKyverno CEL로 :latest · PrivEsc 누락 차단", "kyverno", False),
        ("Demo 5 · Velero 네임스페이스 DR", "make demo-velero", "dr-drill 네임스페이스 + local-path PVC 생성\nKopia S3 백업 후 네임스페이스 완전 삭제\nVelero Restore로 파드 + /data/proof.txt 복원", "velero", False),
        ("Demo 6 · Vault SSH CA 단기 인증서", "make demo-ssh", "authorized_keys 미등록 일회용 키 차단 확인\nVault ssh-client-signer로 5m 인증서 서명\nPasswordAuth=no 상태에서 wk-1·cp-1·ops 로그인", "vault", True),
    ]
    for idx, (dt, cmd, body, dic, ddark) in enumerate(demos):
        col, row = idx % 3, idx // 3
        dx = 152 + col * 468
        dy = 306 + row * 256
        d.box(dx, dy, 448, 240, fill=BG_WHITE, stroke=STROKE_DARK, stroke_weight=1.3, radius=0)
        d.icon(dx + 14, dy + 14, 34, dic, dark_bg=ddark)
        d.text(dx + 58, dy + 13, dt, size=13.8, weight=700, color=TEXT_MAIN, width=376)
        d.box(dx + 58, dy + 38, 174, 24, fill=BG_WHITE, stroke=STROKE_DARK, stroke_weight=1.0, radius=0)
        d.text(dx + 60, dy + 42.5, cmd, size=11.4, weight=700, color=TEXT_MAIN, width=170, center=True)
        d.box(dx + 14, dy + 74, 420, 1.0, fill=STROKE_DARK, stroke=STROKE_DARK, stroke_weight=0, radius=0)
        d.text(dx + 18, dy + 92, body, size=12.6, weight=400, color=TEXT_MAIN, width=412)

    d.footer(
        "접속 엔드포인트: Order http://order.macprod.internal | ArgoCD http://argocd.macprod.internal | Grafana http://grafana.macprod.internal (admin/admin) | Gitea :3000 | Zot :5000 | Vault :8200"
    )
    d.flush("slide-04")
    return fid


# ===========================================================================
# SLIDE 5: Tech Stack Role Catalog (1/2) — L0~L4 Infra, Ops & K8s Core
# ===========================================================================
def build_slide_05(mcp: FigCraftMCP, icons: dict[str, str]) -> int:
    pid = mcp.run_cmd("page.add", {})["id"]
    mcp.run_cmd("page.select", {"id": pid})
    mcp.run_cmd("page.rename", {"name": "05-Stack-Roles-Infra-Core"})
    fid = mcp.create_frame("slide-05-tech-stack-roles-infra-core")
    d = StackCanvas(mcp, fid, icons)

    d.slide_title(
        "Fig. 5 / 6",
        "Fig. 5 — 기술 스택별 역할 총람 [1/2]: L0~L4 하드웨어 · 하이퍼바이저 · 외부 평면 · K8s 코어",
        "하부 계층에 배치된 모든 기술 스택(15종)이 정확히 무슨 역할을 수행하며 어디에 정의·상주하는지 스택 단위로 정리",
    )

    d.layer_tag(102, 732, "기술\n역할\n[1/2]")

    cols = [
        (
            "L0~L3 · 물리 · 하이퍼바이저 · IaC · 런타임",
            [
                (
                    "Apple M4 Max (16C / 128 GB)",
                    "L0 · Host",
                    "• 역할: 단일 물리 ARM64 서버(969 Gi SSD, macOS 15.7.4)\n• 배분: 7 VM 총 17 vCPU · 48 GB RAM 수용 (Swap 0)\n• 여유: 호스트 약 80 GB 가용 및 Sparse 디스크 절약",
                    "apple",
                ),
                (
                    "Cirrus Labs Tart v2.31.0",
                    "L1 · Hypervisor",
                    "• 역할: Apple Virtualization.framework(HVF) 기반 VM 구동\n• 이유: QEMU 에뮬레이션 없이 네이티브 ARM64 커널 7대 실행\n• 정의: scripts/ops-vm-ctl.sh · vmnet 192.168.67.0/24",
                    "tart",
                ),
                (
                    "Terraform v1.5.7 (2-Layer)",
                    "L2 · IaC 선언",
                    "• 역할: L1(local-m4 VM·SSH 키) + L2(platform-state) 분리 선언\n• 이유: VM 생성과 S3 State·Vault·SSH CA 구성을 독립 유지\n• 정의: infra/terraform/local-m4 & platform-state",
                    "terraform",
                ),
                (
                    "Ansible 2.18.14 (Playbook 01~05)",
                    "L2~L3 · 구성",
                    "• 역할: OS 튜닝, ops 스택, kubeadm HA, IP 복구, SSH CA 자동화\n• 이유: 재부팅 후 DHCP IP가 변해도 04-reconcile로 멱등 복구\n• 정의: infra/ansible/playbooks/01~05*.yml",
                    "ansible",
                ),
                (
                    "Docker Compose & containerd",
                    "L3 · Runtime",
                    "• 역할: ops는 Compose+systemd 자가치유, K8s는 containerd 2.2.1\n• 특징: K8s 6노드 모두 Zot :5000 사설 레지스트리 certs.d 등록\n• 정의: ops-stack/docker-compose.yml.j2 · roles/k8s-node",
                    "docker",
                ),
            ],
        ),
        (
            "L3 · macprod-ops 외부 관리 평면 (K8s 비가입)",
            [
                (
                    "HAProxy 3.0-alpine",
                    "ops · L4 LB",
                    "• 역할: K8s API(:6443→cp-1..3) · Ingress(:80→wk:30080) 분산\n• 이유: Tart vmnet 비DHCP VIP 차단 제약을 L4 프록시로 해결\n• 정의: infra/ansible/roles/ops-stack/templates/haproxy.cfg.j2",
                    "haproxy",
                ),
                (
                    "SeaweedFS 4.55 (S3 + Filer)",
                    "ops · S3 / 캐시",
                    "• 역할: :8333 S3(TF State·etcd·CNPG·Velero·Loki) + :8888 Filer\n• 이유: 클러스터 장애 시에도 백업 유실 없는 외부 영속 저장소\n• 치유: 부팅 시 0바이트 .sdx 인덱스 파일 자동 삭제 후 기동",
                    "seaweedfs",
                ),
                (
                    "CNCF Zot v2.1.2 + Trivy",
                    "ops · OCI / 보안",
                    "• 역할: :5000 ARM64 OCI 이미지 레지스트리 + CVE 스캔 게이트\n• 이유: 푸시 전 HIGH/CRITICAL 취약점 차단 및 외부 인터넷 비의존\n• 정의: ops-stack docker-compose · bootstrap-all.sh",
                    "trivy",
                ),
                (
                    "Gitea 1.22 (GitOps SCM)",
                    "ops · Git 저장소",
                    "• 역할: :3000 HTTP / :2222 SSH 사설 Git(gitops · order-service)\n• 이유: ArgoCD 선언 매니페스트와 앱 CI 소스를 클러스터 외부 보존\n• 정의: bootstrap-ops.sh.j2 (초기 미러링·리포 자동 생성)",
                    "gitea",
                ),
                (
                    "HashiCorp Vault 1.18.3",
                    "ops · KMS·SSH CA",
                    "• 역할: :8200 KV v2 시크릿, K8s Auth, SSH CA(1~8h 단기 서명)\n• 특징: File 백엔드·부팅 시 Auto-Unseal·ESO & sshd 연계\n• 정의: terraform/platform-state · 05-configure-ssh-ca.yml",
                    "vault",
                ),
            ],
        ),
        (
            "L4 · Kubernetes 코어 · eBPF 네트워크 · 부하 검증",
            [
                (
                    "Kubernetes v1.32.13 + etcd",
                    "cp-1..3 · HA 코어",
                    "• 역할: kubeadm 3-Master Stacked etcd Raft 쿼럼(1대 장애 생존)\n• 배치: cp-1(Bootstrap/백업 리더), cp-2/3(HA + 02:15 S3 백업)\n• 정의: infra/ansible/playbooks/03-k8s-cluster.yml",
                    "kubernetes",
                ),
                (
                    "Cilium 1.20.5 + Hubble UI",
                    "L4 · eBPF CNI",
                    "• 역할: 커널 eBPF 데이터플레인(kube-proxy 대체) + Hubble 관측\n• 구성: Pod CIDR 10.244.0.0/16 · http://hubble.macprod.internal\n• 정의: platform/bootstrap/install-core.sh#L41-72",
                    "cilium",
                ),
                (
                    "Gateway API v1.6.3 + Envoy",
                    "L4 · L7 Ingress",
                    "• 역할: worker=true 전용 hostNetwork(:30080) L7 HTTP 게이트웨이\n• 기능: *.macprod.internal 라우팅 & Argo Rollouts 카나리 분할\n• 정의: cilium-gateway.yaml · gateway-routes.yaml",
                    "envoy",
                ),
                (
                    "CoreDNS · cert-mgr · local-path",
                    "L4 · 클러스터 기반",
                    "• 역할: *.macprod.internal DNS 해석 · v1.21.3 TLS · v0.0.31 PVC\n• 특징: 재부팅 시 CoreDNS ops_ip 자동 패치 · 기본 StorageClass\n• 정의: install-core.sh · 01-cert-manager.yaml",
                    "cert-manager",
                ),
                (
                    "Grafana k6 v2.4.0 CLI",
                    "ops · 부하 테스트",
                    "• 역할: 클러스터 외부 Bastion에서 HAProxy :80 경유 종단 부하\n• 실측: 30 VU · 3,067 req(p95 226ms) 및 카나리 실패 트래픽 생성\n• 정의: scripts/demos/demo-02-canary-rollback.sh",
                    "k6",
                ),
            ],
        ),
    ]

    for cidx, (col_title, cards) in enumerate(cols):
        cx = 136 + cidx * 478
        d.box(cx, 102, 460, 732, fill=BG_WHITE, stroke=STROKE_DARK, stroke_weight=1.4, radius=0, dashes=[5, 3])
        d.text(cx + 8, 112, col_title, size=12.8, weight=700, color=TEXT_MAIN, width=444, center=True)
        cy = 142
        for title, where, body, ic in cards:
            d.role_card(cx + 12, cy, 436, 126, title, where, body, ic, title_size=12.4, body_size=10.7, icon_size=26)
            cy += 136

    d.footer(
        "기술 스택 역할 [1/2]: L0~L4 모든 스펙·버전 단일 원본 = infra/config/cluster.yaml | 호스트 제어 = Makefile & scripts/ops-vm-ctl.sh"
    )
    d.flush("slide-05")
    return fid


# ===========================================================================
# SLIDE 6: Tech Stack Role Catalog (2/2) — L5~L6 Platform, Observability & App
# ===========================================================================
def build_slide_06(mcp: FigCraftMCP, icons: dict[str, str]) -> int:
    pid = mcp.run_cmd("page.add", {})["id"]
    mcp.run_cmd("page.select", {"id": pid})
    mcp.run_cmd("page.rename", {"name": "06-Stack-Roles-Platform-App"})
    fid = mcp.create_frame("slide-06-tech-stack-roles-platform-app")
    d = StackCanvas(mcp, fid, icons)

    d.slide_title(
        "Fig. 6 / 6",
        "Fig. 6 — 기술 스택별 역할 총람 [2/2]: L5~L6 GitOps · 보안 · DB/DR · 관측성 · 워크로드",
        "워커 풀(macprod-wk-1..3) 위에서 동작하는 GitOps·Zero-Trust 보안·DB/DR·관측성·애플리케이션 스택(12종)의 역할 및 정의 위치",
    )

    d.layer_tag(102, 732, "기술\n역할\n[2/2]")

    cols = [
        (
            "L5 · GitOps 배포 & Zero-Trust 보안",
            [
                (
                    "ArgoCD 10.18.2 (v3.6.2)",
                    "wk · GitOps CD",
                    "• 역할: Gitea gitops 저장소(Wave 0~4)를 감시해 14개 앱 자동 동기화\n• 이유: 명령형 kubectl 대신 선언적 상태 수렴(Self-Heal) 보장\n• 정의: platform/gitops/root-app.yaml · gitops/apps/01~13",
                    "cncf-argo",
                ),
                (
                    "Argo Rollouts 2.43.12",
                    "wk · 카나리 CD",
                    "• 역할: Filer :8888 GatewayAPI 플러그인으로 25%→60% 점진 배포\n• 검증: Demo 2 — PromQL 5xx>10% 감지 시 자동 중단·100/0 원복\n• 정의: apps/order-service/k8s/base/rollout.yaml · analysis",
                    "helm",
                ),
                (
                    "External Secrets 2.15.0",
                    "wk · 시크릿 동기",
                    "• 역할: ClusterSecretStore(vault-backend)로 Vault 시크릿 K8s 주입\n• 주기: 30s/1m 자동 폴링으로 DB 비밀번호·API 키 무중단 회전 지원\n• 정의: platform/gitops/apps/02-external-secrets.yaml",
                    "external-secrets",
                ),
                (
                    "Kyverno 3.10.0 (CEL Gate)",
                    "wk · 어드미션",
                    "• 역할: Kubernetes CEL ValidatingPolicy로 보안 미준수 파드 차단\n• 규칙: :latest 태그 금지, 특권 상승(PrivEsc) 및 리소스 미지정 거부\n• 정의: platform-configs/kyverno-policies.yaml (Demo 4)",
                    "kyverno",
                ),
            ],
        ),
        (
            "L5 · Stateful DB · 백업 DR · 메트릭 관측",
            [
                (
                    "CloudNativePG 0.29.2 (PG 16.6)",
                    "wk-1..3 · HA DB",
                    "• 역할: order-db 3-인스턴스(각 3Gi RWO) 스트리밍 복제 HA 클러스터\n• 복구: Primary 강제 삭제 시 Standby 자동 승격 RTO 24s + Barman S3\n• 정의: gitops/components/cnpg-cluster/order-db.yaml (Demo 3)",
                    "postgresql",
                ),
                (
                    "Velero 12.2.5 + Kopia",
                    "wk · 클러스터 DR",
                    "• 역할: 네임스페이스 매니페스트 & 워커 DaemonSet RWO PVC 백업\n• 검증: Demo 5 — 네임스페이스 완전 삭제 후 파일까지 무손실 복구\n• 정의: platform/gitops/apps/07-velero.yaml (S3 velero-backups)",
                    "velero",
                ),
                (
                    "Prometheus + Alertmanager",
                    "wk · 메트릭 (kps)",
                    "• 역할: 15s 간격 노드·Envoy·order-service(/metrics) 시계열 수집\n• 특징: 1536Mi RWO 영속 + Argo Rollouts 카나리 판정 백엔드 제공\n• 정의: platform/gitops/apps/08-kube-prometheus-stack.yaml",
                    "prometheus",
                ),
                (
                    "Grafana (kps 통합 UI)",
                    "wk · 시각화 포털",
                    "• 역할: Prometheus 메트릭 · Loki 로그 · Tempo 트레이스 단일 대시보드\n• 접속: http://grafana.macprod.internal (Gateway HTTPRoute 연동)\n• 정의: platform/gitops/apps/08-kube-prometheus-stack.yaml",
                    "grafana",
                ),
            ],
        ),
        (
            "L5~L6 · 로그 · 트레이싱 · 앱 · 클라우드 이식성",
            [
                (
                    "Loki 7.7 + Promtail 6.17",
                    "전 노드 · 중앙 로그",
                    "• 역할: 전 노드 파드 로그 수집(Promtail) → Loki 인덱싱 및 S3 청크 저장\n• 용량: SingleBinary 512Mi + 5Gi RWO PVC + loki-chunks 버킷\n• 정의: gitops/apps/09-loki.yaml · 10-promtail.yaml",
                    "loki",
                ),
                (
                    "Tempo 1.24 + OTel 0.182",
                    "wk · 분산 트레이싱",
                    "• 역할: OTel Collector(:4317/:4318)가 OTLP 트레이스 수집 후 Tempo 저장\n• 연계: FastAPI 요청 ↔ PostgreSQL 쿼리까지 end-to-end 추적\n• 정의: gitops/apps/11-tempo.yaml · 12-otel-collector.yaml",
                    "opentelemetry",
                ),
                (
                    "FastAPI (order-service v1.0)",
                    "wk-1..3 · 데모 앱",
                    "• 역할: ARM64 3-레플리카 마이크로서비스(maxSkew:1 균등 배치 실증)\n• 기능: PG DB 쓰기·/metrics·OTel 발행·http://order.macprod.internal\n• 정의: apps/order-service/k8s/base/rollout.yaml",
                    "fastapi",
                ),
                (
                    "SSH CA & EKS Cloud Parity",
                    "7 VM · 보안/이식성",
                    "• 역할: ① 7 VM PasswordAuth=no + Vault 1~8h 인증서 Zero-Trust SSH\n• ② Kustomize local-m4 ↔ cloud-eks 오버레이로 AWS EKS 즉시 이식\n• 정의: 05-configure-ssh-ca.yml · apps/order-service/k8s/overlays",
                    "vault",
                ),
            ],
        ),
    ]

    for cidx, (col_title, cards) in enumerate(cols):
        cx = 136 + cidx * 478
        d.box(cx, 102, 460, 732, fill=BG_WHITE, stroke=STROKE_DARK, stroke_weight=1.4, radius=0, dashes=[5, 3])
        d.text(cx + 8, 112, col_title, size=12.8, weight=700, color=TEXT_MAIN, width=444, center=True)
        cy = 144
        for title, where, body, ic in cards:
            d.role_card(cx + 12, cy, 436, 158, title, where, body, ic, title_size=12.8, body_size=11.3, icon_size=28)
            cy += 172

    d.footer(
        "기술 스택 역할 [2/2]: 전 워크로드 선언은 platform/gitops/ & apps/order-service/ 에 위치 | 상세 근거(ADR) = docs/01-architecture-and-stack-adr.md"
    )
    d.flush("slide-06")
    return fid


def main() -> int:
    if not FIGCRAFT_CLI.exists():
        print(f"ERROR: figcraft-cli not found at {FIGCRAFT_CLI}", file=sys.stderr)
        return 1

    DIAGRAMS_DIR.mkdir(parents=True, exist_ok=True)
    # Remove previous slide PNG/SVG files to keep docs/diagrams/ single-source clean
    for old in DIAGRAMS_DIR.glob("slide-*"):
        if old.is_file():
            old.unlink()

    icons = prepare_icon_cache()
    mcp = FigCraftMCP(FIGCRAFT_CLI, ROOT_DIR)

    try:
        slides = [
            ("slide-01-full-stack-architecture", build_slide_01(mcp, icons)),
            ("slide-02-l0-l4-ops-cp-iac-stack", build_slide_02(mcp, icons)),
            ("slide-03-l5-l6-network-workers", build_slide_03(mcp, icons)),
            ("slide-04-ops-lifecycle-and-demos", build_slide_04(mcp, icons)),
            ("slide-05-tech-stack-roles-infra-core", build_slide_05(mcp, icons)),
            ("slide-06-tech-stack-roles-platform-app", build_slide_06(mcp, icons)),
        ]

        figcraft_path = "docs/diagrams/vol1-infra-handover.figcraft"
        save_res = mcp.tool("save_file", {"path": figcraft_path})
        print(f"[Saved .figcraft] {save_res}")

        for name, fid in slides:
            png_path = f"docs/diagrams/{name}.png"
            svg_path = f"docs/diagrams/{name}.svg"
            res_png = mcp.tool("export", {"ids": [fid], "format": "png", "scale": 2, "path": png_path})
            res_svg = mcp.tool("export", {"ids": [fid], "format": "svg", "path": svg_path})
            print(f"[Exported] {png_path} ({res_png.get('bytes')} bytes), {svg_path} ({res_svg.get('bytes')} bytes)")
    finally:
        mcp.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
