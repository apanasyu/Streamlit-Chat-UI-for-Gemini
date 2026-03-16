from __future__ import annotations

import streamlit as st


def apply_streamlit_theme(page_title: str) -> None:
    st.set_page_config(page_title=page_title, layout="wide")
    st.markdown(
        """
        <style>
        :root {
            --bg: #f4f1ea;
            --card: #fdfbf7;
            --border: #e2dbd1;
            --accent: #d54d36;
            --muted: #8b857f;
            --pill: #f0e6d8;
            --shadow: 0 12px 30px rgba(0,0,0,0.07);
            --font: "DM Sans","Segoe UI","Helvetica Neue",sans-serif;
        }
        .main, [data-testid="stAppViewContainer"] {
            background: radial-gradient(circle at 10% 20%, #fff 0, #f3ece4 35%, #efe7db 70%);
            font-family: var(--font);
        }
        .pill {
            display: inline-block;
            padding: 0.1rem 0.65rem;
            border-radius: 999px;
            background: var(--pill);
            color: var(--muted);
            font-size: 0.85rem;
        }
        .step-card {
            border: 1px solid var(--border);
            background: var(--card);
            padding: 1rem 1.2rem;
            border-radius: 16px;
            box-shadow: var(--shadow);
        }
        .status-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            display: inline-block;
            margin-right: 6px;
        }
        .ready { background: #3bb273; }
        .pending { background: #d7923b; }
        .unconfigured { background: #c9404a; }
        </style>
        """,
        unsafe_allow_html=True,
    )
