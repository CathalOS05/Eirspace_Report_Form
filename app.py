import os
import tempfile
import subprocess
from pathlib import Path
from datetime import date

import pandas as pd
import matplotlib.pyplot as plt
import streamlit as st
from jinja2 import Environment, FileSystemLoader
import shutil
import uuid


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

    template = env.get_template("experiment_template.tex.j2")
    output_tex_path.write_text(template.render(context), encoding="utf-8")


def compile_pdf(tex_path):
    result = subprocess.run(
        ["pdflatex", "-interaction=nonstopmode", str(tex_path.name)],
        cwd=tex_path.parent,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(result.stdout + "\n" + result.stderr)

    return tex_path.with_suffix(".pdf")

def save_uploaded_file(uploaded_file, destination_folder):
    destination_folder.mkdir(parents=True, exist_ok=True)

    safe_name = uploaded_file.name.replace(" ", "_")
    output_path = destination_folder / safe_name

    with open(output_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    return output_path

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

st.title("Experiment Report Generator")

report_date = st.date_input("Report date", value=date.today())

report_type = st.selectbox(
    "Type of report",
    ["Experiment", "Design", "Simulation"]
)

subteam = st.selectbox(
    "Subteam",
    ["Avionics", "Structures", "Propulsion"]
)

experiment_number = st.text_input("Experiment number")
experiment_type = st.text_input("Type of experiment")
report_author = st.text_input("Report author")
participants = st.text_area("Participants")

details = st.text_area("Details")

csv_file = st.file_uploader("Upload CSV (optional)", type=["csv"])

image_files = st.file_uploader(
    "Upload image(s) (optional)",
    type=["png", "jpg", "jpeg", "webp", "bmp", "gif", "tiff", "tif"],
    accept_multiple_files=True,
)

SUBTEAM_CODES = {
    "Avionics": "A",
    "Structures": "S",
    "Propulsion": "P",
}

REPORT_CODES = {
    "Experiment": "E",
    "Design": "D",
    "Simulation": "S",
}

report_code = (
    "R"
    + SUBTEAM_CODES[subteam]
    + REPORT_CODES[report_type]
    + "_"
    + experiment_number.strip()
)

title = report_code

st.info(f"Report ID: {report_code}")

if st.button("Generate PDF"):
    if not title:
        st.error("Please enter a title.")
    else:
        submission_id = uuid.uuid4().hex[:8]
        safe_title = title.replace(" ", "_").replace("/", "_")

        submission_folder = OUTPUT_DIR / f"{safe_title}_{submission_id}"
        documents_folder = submission_folder / "submitted_documents"

        submission_folder.mkdir(parents=True, exist_ok=True)
        documents_folder.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            chart_path = None
            tex_path = tmpdir / "experiment_template.tex"

            table_rows = []
            table_columns = []

            # Optional CSV handling
            if csv_file is not None:
                saved_csv_path = save_uploaded_file(csv_file, documents_folder)
                chart_path = tmpdir / "chart.png"
                df = generate_chart(saved_csv_path, chart_path)

                table_rows = df.head(20).to_dict(orient="records")
                table_columns = list(df.columns)

            # Optional image handling
            saved_image_paths = []
            if image_files:
                for image_file in image_files:
                    saved_image_path = save_uploaded_file(image_file, documents_folder)
                    saved_image_paths.append(saved_image_path)

            context = {
                "report_date": report_date.strftime("%d %B %Y"),
                "report_type": report_type,
                "subteam": subteam,
                "experiment_number": experiment_number,
                "experiment_type": experiment_type,
                "report_author": report_author,
                "participants": participants,
                "details": details,
                "has_csv": csv_file is not None,
                "chart_path": chart_path.as_posix() if chart_path else "",
                "table_rows": table_rows,
                "table_columns": table_columns,
                "has_images": len(saved_image_paths) > 0,
                "image_paths": [p.as_posix() for p in saved_image_paths],
            }

            render_latex(context, tex_path)

            try:
                shutil.copy(
                    BASE_DIR / "static" / "Eirspace_Logo.png",
                    tmpdir / "Eirspace_Logo.png"
                )
                pdf_path = compile_pdf(tex_path)

                final_pdf = submission_folder / f"{safe_title}.pdf"
                final_pdf.write_bytes(pdf_path.read_bytes())

                st.success("PDF generated successfully.")

                st.write(f"Submission folder created:")
                st.code(str(submission_folder))

                st.download_button(
                    "Download PDF",
                    data=final_pdf.read_bytes(),
                    file_name=final_pdf.name,
                    mime="application/pdf",
                )

            except Exception as e:
                st.error("LaTeX compilation failed.")
                st.code(str(e))