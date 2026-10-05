import os
import tempfile

import streamlit as st
from pypdf import PdfReader
from dotenv import load_dotenv
from langchain_google_genai import (
    ChatGoogleGenerativeAI,
    GoogleGenerativeAIEmbeddings
)
from langchain_text_splitters import CharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_classic.chains.question_answering import load_qa_chain

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

load_dotenv()

# API key is always read from the .env file — never from the user.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

st.set_page_config(page_title="PDF Q&A with Gemini", page_icon="📄")
st.title("📄 PDF Q&A with Gemini")

if not GEMINI_API_KEY:
    st.error(
        "GEMINI_API_KEY not found. Please add it to a `.env` file "
        "in the project root, e.g.\n\nGEMINI_API_KEY=your_key_here"
    )
    st.stop()

# Make sure downstream LangChain/Google libraries can see the key too.
os.environ["GOOGLE_API_KEY"] = GEMINI_API_KEY

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

if "document_search" not in st.session_state:
    st.session_state.document_search = None
if "chain" not in st.session_state:
    st.session_state.chain = None
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []  # list of (question, answer)


@st.cache_resource(show_spinner=False)
def build_llm():
    return ChatGoogleGenerativeAI(
        model="gemini-3.5-flash-lite",
        temperature=0,
        google_api_key=GEMINI_API_KEY,
    )


@st.cache_resource(show_spinner=False)
def build_embeddings():
    return GoogleGenerativeAIEmbeddings(
        model="models/gemini-embedding-001",
        google_api_key=GEMINI_API_KEY,
    )


def process_pdf(uploaded_file):
    """Extract text, split into chunks, and build a FAISS vector store."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(uploaded_file.read())
        tmp_path = tmp.name

    try:
        pdfreader = PdfReader(tmp_path)
        raw_text = ""
        for page in pdfreader.pages:
            content = page.extract_text()
            if content:
                raw_text += content + "\n"
    finally:
        os.remove(tmp_path)

    if not raw_text.strip():
        return None, 0

    text_splitter = CharacterTextSplitter(
        separator="\n",
        chunk_size=800,
        chunk_overlap=200,
        length_function=len,
    )
    texts = text_splitter.split_text(raw_text)

    embeddings = build_embeddings()
    document_search = FAISS.from_texts(texts, embeddings)

    return document_search, len(texts)


# ---------------------------------------------------------------------------
# Sidebar: upload + process
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("Upload a PDF")
    uploaded_file = st.file_uploader("Choose a PDF file", type=["pdf"])

    if uploaded_file is not None:
        if st.button("Process PDF", type="primary"):
            with st.spinner("Extracting text and building the search index..."):
                document_search, num_chunks = process_pdf(uploaded_file)

            if document_search is None:
                st.error("No extractable text was found in this PDF.")
            else:
                st.session_state.document_search = document_search
                st.session_state.chain = load_qa_chain(build_llm(), chain_type="stuff")
                st.session_state.chat_history = []
                st.success(f"PDF processed successfully into {num_chunks} chunks.")

    if st.session_state.document_search is not None:
        st.info("✅ PDF is ready for questions.")

# ---------------------------------------------------------------------------
# Main area: ask questions
# ---------------------------------------------------------------------------

if st.session_state.document_search is None:
    st.write("👈 Upload and process a PDF from the sidebar to get started.")
else:
    query = st.text_input("Ask a question about the PDF:")

    if st.button("Ask") and query.strip():
        with st.spinner("Searching document and generating answer..."):
            docs = st.session_state.document_search.similarity_search(query, k=4)
            answer = st.session_state.chain.invoke(
                {"input_documents": docs, "question": query}
            )
        st.session_state.chat_history.append((query, answer["output_text"]))

    # Display chat history, most recent first
    for q, a in reversed(st.session_state.chat_history):
        st.markdown(f"**Q: {q}**")
        st.markdown(f"A: {a}")
        st.divider()