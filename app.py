import os
import tempfile
import subprocess
from pathlib import Path
from datetime import date

import pandas as pd
import matplotlib.pyplot as plt
import streamlit as st
from jinja2 import Environment, FileSystemLoader


BASE_DIR = Path(__file__).parent
TEMPLATE_DIR = BASE_DIR / "templates"
OUTPUT_DIR = BASE_DIR / "outputs"
CHART_DIR = BASE_DIR / "charts"

OUTPUT_DIR.mkdir(exist_ok=True)
CHART_DIR.mkdir(exist_ok=True)


def generate_chart(csv_file, output_path):
    df = pd.read_csv(csv_file)

    # Assumes first column is x-axis and second column is y-axis
    x_col = df.columns[0]
    y_col = df.columns[1]

    plt.figure(figsize=(8, 4.5))
    plt.plot(df[x_col], df[y_col], marker="o")
    plt.title(f"{y_col} by {x_col}")
    plt.xlabel(x_col)
    plt.ylabel(y_col)
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()

    return df


def render_latex(context, output_tex_path):
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        block_start_string="((*",
        block_end_string="*))",
        variable_start_string="(((",
        variable_end_string=")))",
        comment_start_string="((=",
        comment_end_string="=))",
    )

    template = env.get_template("report.tex.j2")
    output_tex_path.write_text(template.render(context), encoding="utf-8")


def compile_pdf(tex_path):
    subprocess.run(
        ["latexmk", "-pdf", "-interaction=nonstopmode", str(tex_path)],
        cwd=tex_path.parent,
        check=True,
    )

    return tex_path.with_suffix(".pdf")


def upload_to_google_drive(pdf_path):
    """
    TODO:
    Add Google Drive upload logic here.

    Use:
    - google-api-python-client
    - google-auth
    - google-auth-oauthlib

    You will need:
    - Google Cloud project
    - Drive API enabled
    - OAuth credentials or service account
    - Target folder ID
    """
    st.info(f"PDF generated locally: {pdf_path}")
    return None


st.set_page_config(page_title="PDF Report Generator", layout="centered")

st.title("PDF Report Generator")

report_date = st.date_input("Report date", value=date.today())
title = st.text_input("Report title")
detail_1 = st.text_input("Detail 1")
detail_2 = st.text_input("Detail 2")
detail_3 = st.text_area("Additional notes")

csv_file = st.file_uploader("Upload CSV", type=["csv"])

if st.button("Generate PDF"):
    if not title:
        st.error("Please enter a title.")
    elif csv_file is None:
        st.error("Please upload a CSV file.")
    else:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            chart_path = tmpdir / "chart.png"
            tex_path = tmpdir / "report.tex"

            df = generate_chart(csv_file, chart_path)

            context = {
                "report_date": report_date.strftime("%d %B %Y"),
                "title": title,
                "detail_1": detail_1,
                "detail_2": detail_2,
                "detail_3": detail_3,
                "chart_path": chart_path.as_posix(),
                "table_rows": df.head(20).to_dict(orient="records"),
                "table_columns": list(df.columns),
            }

            render_latex(context, tex_path)

            try:
                pdf_path = compile_pdf(tex_path)
                final_pdf = OUTPUT_DIR / f"{title.replace(' ', '_')}.pdf"
                final_pdf.write_bytes(pdf_path.read_bytes())

                upload_to_google_drive(final_pdf)

                st.success("PDF generated successfully.")
                st.download_button(
                    "Download PDF",
                    data=final_pdf.read_bytes(),
                    file_name=final_pdf.name,
                    mime="application/pdf",
                )

            except subprocess.CalledProcessError:
                st.error("LaTeX compilation failed. Check your template.")