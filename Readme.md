# Autonomous AI Document Generator Agent

An autonomous AI agent built using **FastAPI**, **Python**, and **Google Gemini** that understands a natural language request, creates its own execution plan (TODO list), generates a structured business document, reviews the generated content, and exports the final output as a **Microsoft Word (.docx)** file.

This project was developed as part of an **AI Engineer Assignment** to demonstrate autonomous planning, software engineering principles, multi-agent architecture, and end-to-end AI workflow automation.

---

#  Features

* Accepts natural language document requests
* Automatically identifies document type
* Generates its own execution plan (TODO list)
* Detects missing information
* Makes intelligent assumptions when required
* Generates document section by section
* Reviews generated content before finalizing
* Exports a professional Microsoft Word (.docx) document
* REST API built using FastAPI
* Hybrid AI architecture (Python + Gemini)

---

#  Architecture

```
                User Request
                     │
                     ▼
             FastAPI Endpoint
                     │
                     ▼
           Request Validation
                (Python)
                     │
                     ▼
             Orchestrator Agent
                     │
      ┌──────────────┼───────────────┐
      ▼              ▼               ▼
 Planner Agent   Content Agent   Review Agent
                     │
                     ▼
          Document Generator
                     │
                     ▼
              Word (.docx) File
```

---

#  Agents

## 1. Planner Agent

Responsible for understanding the request and preparing the execution plan.

Responsibilities:

* Analyze user request
* Detect document type
* Load document template
* Extract important information
* Detect missing fields
* Generate assumptions (if needed)
* Create execution plan (TODO list)

Output:

```
ExecutionPlan
```

---

## 2. Content Generation Agent

Generates one section of the document at a time.

Responsibilities:

* Read each task from Execution Plan
* Generate section content
* Store generated sections
* Update task status

---

## 3. Review Agent

Checks the quality of generated content.

Responsibilities:

* Detect missing sections
* Detect very short content
* Review section quality
* Regenerate sections if required
* Approve final content

---

## 4. Document Generator

Creates the final Microsoft Word document.

Responsibilities:

* Read all approved sections
* Apply formatting
* Create headings
* Save .docx file

---

#  Project Structure

```
project/
│
├── app.py
├── config.py
├── requirements.txt
│
├── agents/
│   ├── orchestrator.py
│   ├── planner.py
│   ├── content_generator.py
│   ├── reviewer.py
│   └── document_generator.py
│
├── llm/
│   ├── llm_client.py
│   └── prompts.py
│
├── models/
│   ├── request.py
│   ├── response.py
│   └── planner_models.py
│
├── templates/
│   └── document_templates.py
│
├── utils/
│   ├── constants.py
│   ├── validators.py
│   └── file_utils.py
│
└── outputs/
```

---

#  Hybrid AI Architecture

The project follows a **Python-first, LLM-when-needed** approach.

## Python Handles

* Request validation
* Loading document templates
* Creating execution plan
* Task generation
* Missing field detection
* Response generation
* DOCX generation
* File management

## Gemini Handles

* Document classification
* Semantic understanding
* Information extraction (fallback)
* Assumption generation
* Section writing
* Content review

This minimizes unnecessary LLM usage and improves speed, cost, and reliability.

---

#  Supported Document Types

* Business Proposal
* Project Plan
* Business Report
* Meeting Minutes
* Technical Design
* Standard Operating Procedure (SOP)
* Product Specification
* Generic Report

---

#  Workflow

```
User Request
      │
      ▼
Validate Request
      │
      ▼
Planner Agent
      │
      ▼
Execution Plan
      │
      ▼
Content Generation
      │
      ▼
Review Agent
      │
      ▼
Document Generator
      │
      ▼
Generated Word Document
      │
      ▼
API Response
```

---

#  API

### POST /agent

Request

```json
{
    "request":"Create a business proposal for an AI healthcare startup targeting investors."
}
```

Example Response

```json
{
    "status":"success",
    "message":"Document generated successfully.",
    "file_path":"outputs/business_proposal.docx",
    "plan_summary":{...}
}
```

---

# 🛠 Technologies Used

* Python
* FastAPI
* Google Gemini API
* Pydantic
* python-docx
* Logging
* Dataclasses

---

#  Engineering Improvement Implemented

### Multi-Step Autonomous Planning

Instead of generating the complete document directly, the system first creates an **Execution Plan** containing ordered tasks.

Example:

```
Task 1 → Executive Summary

Task 2 → Problem Statement

Task 3 → Market Analysis

Task 4 → Pricing

Task 5 → Conclusion
```

Each task is executed independently, making the system more modular, scalable, and easier to debug.

---

#  Example Requests

### Business Proposal

```
Create a business proposal for an AI-powered healthcare startup targeting investors.
```

### Project Plan

```
Create a project plan for migrating an e-commerce application to a microservices architecture.
```

### Technical Design

```
Design a scalable notification system for an online banking application.
```

---

#  Running the Project

Install dependencies

```bash
pip install -r requirements.txt
```

Run the FastAPI server

```bash
uvicorn app:app --reload
```

Open Swagger UI

```
http://127.0.0.1:8000/docs
```

---

#  Future Improvements

* Conversation Memory
* Retrieval-Augmented Generation (RAG)
* Tool Calling
* Multi-model Support
* Streaming Responses
* Human-in-the-loop Review
* PDF Export
* Cloud Storage Integration

---


