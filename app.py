import shutil
import subprocess
import tempfile
import uuid
from datetime import date
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st
from jinja2 import Environment, FileSystemLoader


# =========================================================
# Folder paths
# =========================================================

BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / "templates"
OUTPUT_DIR = BASE_DIR / "outputs"
STATIC_DIR = BASE_DIR / "static"

TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)


# =========================================================
# Report configuration
# =========================================================

SUBTEAMS = [
    "Avionics",
    "Structures",
    "Propulsion",
    "Recovery",
    "General",
]

SUBTEAM_CODES = {
    "Avionics": "A",
    "Structures": "S",
    "Propulsion": "P",
    "Recovery": "R",
    "General": "G",
}

REPORT_TYPES = [
    "Testing Report",
    "Simulation Report",
    "Design Report",
    "Project Outline Report",
    "Project Completion Report",
]

REPORT_CODES = {
    "Testing Report": "T",
    "Simulation Report": "S",
    "Design Report": "D",
    "Project Outline Report": "O",
    "Project Completion Report": "C",
}

REPORT_TEMPLATES = {
    "Testing Report": "testing_report.tex.j2",
    "Simulation Report": "simulation_report.tex.j2",
    "Design Report": "design_report.tex.j2",
    "Project Outline Report": "project_outline_report.tex.j2",
    "Project Completion Report": "project_completion_report.tex.j2",
}


# =========================================================
# Utility functions
# =========================================================

def latex_escape(value):
    """
    Escape characters that have special meaning in LaTeX.
    """
    if value is None:
        return ""

    value = str(value)

    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }

    escaped = "".join(
        replacements.get(character, character)
        for character in value
    )

    escaped = escaped.replace("\r\n", "\n")
    escaped = escaped.replace("\r", "\n")
    escaped = escaped.replace("\n", "\n\n")

    return escaped


def safe_filename(value):
    """
    Convert text into a safe filename.
    """
    value = str(value).strip()

    for character in '<>:"/\\|?*':
        value = value.replace(character, "_")

    value = value.replace(" ", "_")

    while "__" in value:
        value = value.replace("__", "_")

    return value.strip("._") or "report"


def create_report_code(subteam, report_type, report_number):
    """
    Create a code such as RST_001.
    """
    return (
        "R"
        + SUBTEAM_CODES[subteam]
        + REPORT_CODES[report_type]
        + "_"
        + report_number.strip()
    )


def save_uploaded_file(uploaded_file, destination_folder):
    """
    Save a Streamlit uploaded file.
    """
    destination_folder.mkdir(parents=True, exist_ok=True)

    original_name = Path(uploaded_file.name).name
    safe_name = safe_filename(original_name)

    extension = Path(original_name).suffix.lower()

    if extension and not safe_name.lower().endswith(extension):
        safe_name = f"{Path(safe_name).stem}{extension}"

    output_path = destination_folder / safe_name

    counter = 1

    while output_path.exists():
        output_path = destination_folder / (
            f"{Path(safe_name).stem}_{counter}"
            f"{Path(safe_name).suffix}"
        )
        counter += 1

    output_path.write_bytes(uploaded_file.getbuffer())

    return output_path


def generate_chart(csv_path, output_path):
    """
    Generate a basic chart from the first two CSV columns.
    """
    dataframe = pd.read_csv(csv_path)

    if len(dataframe.columns) < 2:
        raise ValueError(
            "The CSV must contain at least two columns."
        )

    x_column = dataframe.columns[0]
    y_column = dataframe.columns[1]

    plt.figure(figsize=(8, 4.5))
    plt.plot(
        dataframe[x_column],
        dataframe[y_column],
        marker="o",
    )
    plt.title(f"{y_column} by {x_column}")
    plt.xlabel(x_column)
    plt.ylabel(y_column)
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(
        output_path,
        dpi=200,
        bbox_inches="tight",
    )
    plt.close()

    return dataframe


def create_jinja_environment():
    """
    Create the Jinja environment used for LaTeX templates.
    """
    environment = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        block_start_string="((*",
        block_end_string="*))",
        variable_start_string="(((",
        variable_end_string=")))",
        comment_start_string="((=",
        comment_end_string="=))",
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )

    environment.filters["latex_escape"] = latex_escape

    return environment


def render_latex(
    context,
    output_tex_path,
    template_filename,
):
    """
    Render the selected LaTeX template.
    """
    environment = create_jinja_environment()
    template = environment.get_template(template_filename)

    rendered_document = template.render(context)

    output_tex_path.write_text(
        rendered_document,
        encoding="utf-8",
    )


def compile_pdf(tex_path):
    """
    Compile the LaTeX file twice using pdflatex.
    """
    command = [
        "pdflatex",
        "-interaction=nonstopmode",
        "-halt-on-error",
        tex_path.name,
    ]

    for _ in range(2):
        result = subprocess.run(
            command,
            cwd=tex_path.parent,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            log_path = tex_path.with_suffix(".log")

            if log_path.exists():
                log_text = log_path.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
            else:
                log_text = "No LaTeX log was created."

            raise RuntimeError(
                f"{result.stdout}\n\n"
                f"{result.stderr}\n\n"
                f"{log_text}"
            )

    pdf_path = tex_path.with_suffix(".pdf")

    if not pdf_path.exists():
        raise FileNotFoundError(
            "The PDF was not created."
        )

    return pdf_path


def short_text_area(
    label,
    help_text=None,
    height=110,
    placeholder=None,
):
    return st.text_area(
        label,
        help=help_text,
        height=height,
        placeholder=placeholder,
    )


# =========================================================
# Short report forms
# =========================================================

def testing_report_form():
    sections = {}

    sections["objective"] = short_text_area(
        "Purpose of test",
        "Briefly state what was being tested and why.",
    )

    sections["setup"] = short_text_area(
        "Setup and procedure",
        "Briefly describe the equipment and method used.",
        height=130,
    )

    sections["results"] = short_text_area(
        "Main results",
        "Record the important measurements or observations.",
        height=130,
    )

    sections["conclusion"] = short_text_area(
        "Conclusion and next action",
        "State whether the test was successful and what happens next.",
    )

    return sections


def simulation_report_form():
    sections = {}

    sections["objective"] = short_text_area(
        "Purpose of simulation",
        "Briefly state what the simulation was intended to investigate.",
    )

    sections["model"] = short_text_area(
        "Model and assumptions",
        "State the software, model used and important assumptions.",
        height=130,
    )

    sections["results"] = short_text_area(
        "Main results",
        "Record the most important outputs.",
        height=130,
    )

    sections["conclusion"] = short_text_area(
        "Conclusion and next action",
        "State what the results mean and any required follow-up.",
    )

    return sections


def design_report_form():
    sections = {}

    sections["goal"] = short_text_area(
        "Design goal",
        "Briefly describe what the design must achieve.",
    )

    sections["requirements"] = short_text_area(
        "Key requirements",
        "List the most important technical or practical requirements.",
    )

    sections["design"] = short_text_area(
        "Selected design",
        "Briefly describe the chosen design and why it was selected.",
        height=130,
    )

    sections["verification"] = short_text_area(
        "Verification and next action",
        "State how the design will be checked and what remains to be done.",
    )

    return sections


def project_outline_report_form():
    sections = {}

    sections["main_goal"] = short_text_area(
        "Main goal",
        "State the main outcome of the project.",
    )

    sections["description"] = short_text_area(
        "Short description",
        "Briefly describe the work to be completed.",
        height=130,
    )

    sections["responsible_person"] = st.text_input(
        "Person responsible",
        placeholder="Project lead",
    )

    sections["supporting_members"] = st.text_input(
        "Supporting members",
        placeholder="Optional",
    )

    sections["target_date"] = st.date_input(
        "Target completion date",
        value=date.today(),
        key="outline_target_date",
    )

    sections["status"] = st.selectbox(
        "Current status",
        [
            "Not started",
            "Planning",
            "In progress",
            "On hold",
        ],
        key="outline_status",
    )

    sections["notes"] = short_text_area(
        "Additional notes",
        "Optional short notes, dependencies or relevant information.",
        height=90,
    )

    return sections


def project_completion_report_form():
    sections = {}

    sections["main_goal"] = short_text_area(
        "Original project goal",
        "State what the project was intended to achieve.",
    )

    sections["description"] = short_text_area(
        "Work completed",
        "Briefly describe what was completed.",
        height=130,
    )

    sections["responsible_person"] = st.text_input(
        "Person responsible",
        placeholder="Project lead",
    )

    sections["supporting_members"] = st.text_input(
        "Supporting members",
        placeholder="Optional",
    )

    sections["completion_date"] = st.date_input(
        "Completion date",
        value=date.today(),
        key="completion_date",
    )

    sections["outcome"] = st.selectbox(
        "Project outcome",
        [
            "Completed successfully",
            "Completed with changes",
            "Partially completed",
            "Cancelled",
        ],
        key="project_outcome",
    )

    sections["result"] = short_text_area(
        "Final result",
        "Briefly record the final outcome, hardware or documents produced.",
        height=110,
    )

    sections["notes"] = short_text_area(
        "Remaining actions or notes",
        "Optional short record of outstanding work or lessons learned.",
        height=90,
    )

    return sections


# =========================================================
# Streamlit interface
# =========================================================

st.set_page_config(
    page_title="Eirspace Report Generator",
    layout="centered",
)

st.title("Eirspace Report Generator")

st.caption(
    "Create short, consistent engineering and project reports."
)

report_type = st.selectbox(
    "Report type",
    REPORT_TYPES,
)

subteam = st.selectbox(
    "Department",
    SUBTEAMS,
)

report_number = st.text_input(
    "Report number",
    placeholder="For example: 001",
)

report_date = st.date_input(
    "Date of report",
    value=date.today(),
)

report_author = st.text_input(
    "Report author",
)

participants = st.text_input(
    "Other participants",
    placeholder="Optional",
)

if report_type == "Testing Report":
    report_subject = st.text_input(
        "Test title",
        placeholder="For example: Airframe Compression Test",
    )

elif report_type == "Simulation Report":
    report_subject = st.text_input(
        "Simulation title",
        placeholder="For example: Fin Flutter Simulation",
    )

elif report_type == "Design Report":
    report_subject = st.text_input(
        "Design title",
        placeholder="For example: Avionics Bay Design",
    )

elif report_type == "Project Outline Report":
    report_subject = st.text_input(
        "Project title",
        placeholder="For example: Composite Nosecone Development",
    )

else:
    report_subject = st.text_input(
        "Completed project title",
        placeholder="For example: Composite Nosecone Development",
    )


st.divider()
st.subheader("Report details")

if report_type == "Testing Report":
    report_sections = testing_report_form()

elif report_type == "Simulation Report":
    report_sections = simulation_report_form()

elif report_type == "Design Report":
    report_sections = design_report_form()

elif report_type == "Project Outline Report":
    report_sections = project_outline_report_form()

else:
    report_sections = project_completion_report_form()


st.divider()
st.subheader("Attachments")

csv_file = st.file_uploader(
    "Upload CSV data",
    type=["csv"],
    help="Optional. A chart and short table will be added to the report.",
)

image_files = st.file_uploader(
    "Upload images",
    type=[
        "png",
        "jpg",
        "jpeg",
        "webp",
        "bmp",
        "tif",
        "tiff",
    ],
    accept_multiple_files=True,
    help="Optional. Upload photographs, screenshots, drawings or plots.",
)


report_code = create_report_code(
    subteam,
    report_type,
    report_number,
)

st.info(f"Report ID: {report_code}")


# =========================================================
# PDF generation
# =========================================================

if st.button(
    "Generate PDF",
    type="primary",
    use_container_width=True,
):
    errors = []

    if not report_number.strip():
        errors.append("Enter a report number.")

    if not report_subject.strip():
        errors.append("Enter a report title.")

    if not report_author.strip():
        errors.append("Enter the report author.")

    if errors:
        for error in errors:
            st.error(error)

    else:
        submission_id = uuid.uuid4().hex[:8]
        safe_report_code = safe_filename(report_code)

        submission_folder = (
            OUTPUT_DIR
            / f"{safe_report_code}_{submission_id}"
        )

        documents_folder = (
            submission_folder
            / "submitted_documents"
        )

        submission_folder.mkdir(
            parents=True,
            exist_ok=True,
        )

        documents_folder.mkdir(
            parents=True,
            exist_ok=True,
        )

        try:
            with tempfile.TemporaryDirectory() as temporary_directory:
                working_directory = Path(temporary_directory)

                template_filename = REPORT_TEMPLATES[report_type]
                tex_filename = template_filename.removesuffix(".j2")
                tex_path = working_directory / tex_filename

                chart_path = None
                table_rows = []
                table_columns = []

                # CSV
                if csv_file is not None:
                    saved_csv_path = save_uploaded_file(
                        csv_file,
                        documents_folder,
                    )

                    chart_path = working_directory / "chart.png"

                    dataframe = generate_chart(
                        saved_csv_path,
                        chart_path,
                    )

                    table_rows = dataframe.head(20).to_dict(
                        orient="records"
                    )

                    table_columns = list(dataframe.columns)

                # Images
                working_image_paths = []
                saved_image_paths = []

                for image_file in image_files or []:
                    saved_image_path = save_uploaded_file(
                        image_file,
                        documents_folder,
                    )

                    saved_image_paths.append(saved_image_path)

                    working_image_path = (
                        working_directory
                        / saved_image_path.name
                    )

                    shutil.copy2(
                        saved_image_path,
                        working_image_path,
                    )

                    working_image_paths.append(
                        working_image_path
                    )

                # Logo
                logo_source = (
                    STATIC_DIR
                    / "Eirspace_Logo.png"
                )

                logo_path = ""

                if logo_source.exists():
                    logo_destination = (
                        working_directory
                        / "Eirspace_Logo.png"
                    )

                    shutil.copy2(
                        logo_source,
                        logo_destination,
                    )

                    logo_path = logo_destination.as_posix()

                # Convert date fields inside report_sections.
                formatted_sections = {}

                for key, value in report_sections.items():
                    if isinstance(value, date):
                        formatted_sections[key] = value.strftime(
                            "%d %B %Y"
                        )
                    else:
                        formatted_sections[key] = value

                context = {
                    "report_code": report_code,
                    "report_type": report_type,
                    "report_title": report_subject,
                    "report_subject": report_subject,
                    "report_number": report_number,
                    "report_date": report_date.strftime(
                        "%d %B %Y"
                    ),
                    "subteam": subteam,
                    "department": subteam,
                    "report_author": report_author,
                    "participants": participants,
                    "sections": formatted_sections,
                    "has_csv": csv_file is not None,
                    "chart_path": (
                        chart_path.as_posix()
                        if chart_path
                        else ""
                    ),
                    "table_rows": table_rows,
                    "table_columns": table_columns,
                    "has_images": len(
                        working_image_paths
                    ) > 0,
                    "image_paths": [
                        path.as_posix()
                        for path in working_image_paths
                    ],
                    "logo_path": logo_path,
                }

                render_latex(
                    context,
                    tex_path,
                    template_filename,
                )

                pdf_path = compile_pdf(tex_path)

                final_pdf_path = (
                    submission_folder
                    / f"{safe_report_code}.pdf"
                )

                final_pdf_path.write_bytes(
                    pdf_path.read_bytes()
                )

                # Save rendered LaTeX for future editing.
                final_tex_path = (
                    submission_folder
                    / f"{safe_report_code}.tex"
                )

                final_tex_path.write_bytes(
                    tex_path.read_bytes()
                )

                st.success(
                    "PDF generated successfully."
                )

                st.download_button(
                    "Download PDF",
                    data=final_pdf_path.read_bytes(),
                    file_name=final_pdf_path.name,
                    mime="application/pdf",
                    use_container_width=True,
                )

                with st.expander(
                    "Saved report location"
                ):
                    st.code(str(submission_folder))

        except FileNotFoundError as error:
            st.error(
                "A required file could not be found."
            )
            st.code(str(error))

        except subprocess.SubprocessError as error:
            st.error(
                "LaTeX could not be run."
            )
            st.code(str(error))

        except Exception as error:
            st.error(
                "The report could not be generated."
            )
            st.code(str(error))