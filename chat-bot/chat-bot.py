from flask import Flask, request, jsonify
import os
import config
from config import OPENAI_API_KEY
import logging
import nltk

# Ensure NLTK has the required resource.
nltk.download('averaged_perceptron_tagger', quiet=True)

# Updated imports to remove deprecation warnings.
from langchain_community.llms import OpenAI
from langchain_community.document_loaders import UnstructuredURLLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings

# Setup logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

# ---------------- Constants ----------------
KNOWLEDGE_BASE_URLS = [
    'https://www.techinterviewhandbook.org/software-engineering-interview-guide/',
    'https://www.techinterviewhandbook.org/resume/',
    'https://www.techinterviewhandbook.org/coding-interview-prep/',
    'https://www.techinterviewhandbook.org/coding-interview-rubrics/',
    'https://www.techinterviewhandbook.org/system-design/',
    'https://www.techinterviewhandbook.org/behavioral-interview/'
]

# ---------------- Helper Functions ----------------

def create_model():
    logging.debug("Creating language model using OpenAI API.")
    return OpenAI(temperature=0, openai_api_key=config.OPENAI_API_KEY)

def build_vector_store():
    logging.debug("Building vector store from knowledge base URLs.")
    docs = []
    for url in KNOWLEDGE_BASE_URLS:
        logging.debug(f"Loading documents from URL: {url}")
        loader = UnstructuredURLLoader(urls=[url])
        docs.extend(loader.load())
    
    logging.debug("Splitting documents into smaller chunks.")
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=250, chunk_overlap=0)
    split_docs = text_splitter.split_documents(docs)
    
    logging.debug("Creating embeddings for the documents.")
    embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    
    logging.debug("Building vector store using FAISS.")
    vectorstore = FAISS.from_documents(split_docs, embeddings)
    return vectorstore

def grade_question(question):
    logging.debug(f"Grading question relevance for: {question}")
    lower_q = question.lower()
    if "software" in lower_q or "coding" in lower_q or "interview" in lower_q:
        logging.debug("Question graded as relevant.")
        return "continue"
    logging.debug("Question graded as not relevant.")
    return "exit"

def grade_document(question, doc):
    logging.debug("Grading document relevance for a retrieved document chunk.")
    if any(word in doc.page_content.lower() for word in question.lower().split()):
        logging.debug("Document graded as relevant.")
        return "yes"
    logging.debug("Document graded as not relevant.")
    return "no"

def generate_answer(question, docs, model):
    logging.debug("Generating answer using relevant documents as context.")
    context = "\n\n".join([doc.page_content for doc in docs])
    prompt = (
        "Using the following context, answer the question.\n\n"
        f"Context:\n{context}\n\n"
        f"Question: {question}\n"
        "Answer:"
    )
    return model(prompt)

# ---------------- Global Initialization ----------------

# Build the vector store once on startup and store it in a global variable.
vector_store = None

def initialize_vector_store():
    global vector_store
    logging.info("Initializing vector store on startup...")
    vector_store = build_vector_store()
    logging.info("Vector store built successfully.")

# ---------------- Flask Endpoint ----------------

@app.route("/chat", methods=["POST"])
def chat():
    logging.debug("Received /chat POST request.")
    try:
        data = request.get_json()
        logging.debug(f"Request JSON: {data}")
        question = data.get("question")
        if not question:
            logging.error("No question provided in the request.")
            return jsonify({"error": "No question provided"}), 400

        logging.debug(f"Question received: {question}")
        # Step 1: Create the language model.
        model = create_model()

        # Step 2: Grade the question.
        question_grade = grade_question(question)
        if question_grade.strip().lower() == "exit":
            logging.info("Question is not relevant to the domain.")
            return jsonify({
                "answer": ("The question does not seem relevant to the Software Engineering and "
                           "Coding Interview domain. Please ask a relevant question!")
            })

        # Step 3: Use the pre-built vector store.
        if vector_store is None:
            logging.error("Vector store is not initialized yet.")
            return jsonify({"error": "Vector store is not ready"}), 503

        # Step 4: Retrieve documents based on the question.
        retrieved_docs = vector_store.similarity_search(question)
        logging.debug(f"Retrieved {len(retrieved_docs)} documents from vector store.")

        # Step 5: Grade each document and filter only the relevant ones.
        relevant_docs = []
        for doc in retrieved_docs:
            if grade_document(question, doc).strip().lower() == "yes":
                relevant_docs.append(doc)
        logging.debug(f"Filtered down to {len(relevant_docs)} relevant documents.")

        if not relevant_docs:
            logging.info("No relevant documents were found for the question.")
            return jsonify({
                "answer": ("No relevant documents were found. Please try a different question "
                           "related to Software Engineering or Coding Interviews.")
            })

        # Step 6: Generate an answer using the relevant documents as context.
        answer = generate_answer(question, relevant_docs, model)
        logging.debug("Answer generated successfully.")
        return jsonify({"answer": answer})
    
    except Exception as e:
        import traceback
        error_message = traceback.format_exc()
        logging.error("Error occurred during /chat processing.")
        logging.error(error_message)
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    # Initialize the vector store before starting the server.
    initialize_vector_store()
    logging.info("Starting Flask server on port 5001.")
    app.run(debug=True, port=5001, host="0.0.0.0")
