"""Knowledge Base Seeder - Fetch and index SET institutional documents"""
import json
import logging
import asyncio
from pathlib import Path
from typing import List, Dict, Optional
import httpx
from bs4 import BeautifulSoup
from document_processor import DocumentProcessor

logger = logging.getLogger(__name__)
ROOT_DIR = Path(__file__).resolve().parent
LOCAL_DATASET_PATH = ROOT_DIR / "datasets" / "krmu_official_knowledge.json"


# K.R. Mangalam University SET official pages to seed
SEED_URLS = [
    {
        "url": "https://www.krmangalam.edu.in/school-of-engineering-and-technology",
        "title": "SET Overview - School of Engineering & Technology",
        "category": "about"
    },
    {
        "url": "https://www.krmangalam.edu.in/programmes",
        "title": "Academic Programmes",
        "category": "programs"
    },
    {
        "url": "https://www.krmangalam.edu.in/about-krmu/the-university",
        "title": "About K.R. Mangalam University",
        "category": "about"
    },
    {
        "url": "https://www.krmangalam.edu.in/computer-science-engineering",
        "title": "Computer Science Engineering",
        "category": "department"
    },
    {
        "url": "https://www.krmangalam.edu.in/mechanical-engineering",
        "title": "Mechanical Engineering",
        "category": "department"
    },
    {
        "url": "https://www.krmangalam.edu.in/civil-engineering",
        "title": "Civil Engineering",
        "category": "department"
    },
    {
        "url": "https://www.krmangalam.edu.in/electrical-electronics-engineering",
        "title": "Electrical & Electronics Engineering",
        "category": "department"
    },
    {
        "url": "https://www.krmangalam.edu.in/placements",
        "title": "Placements & Career Services",
        "category": "placements"
    },
    {
        "url": "https://www.krmangalam.edu.in/admissions",
        "title": "Admissions Information",
        "category": "admissions"
    },
    {
        "url": "https://www.krmangalam.edu.in/infrastructure",
        "title": "Campus Infrastructure & Facilities",
        "category": "facilities"
    }
]

# Sample faculty data
FACULTY_DATA = """
# SET Faculty Directory

## Computer Science & Engineering Department

### Dr. Rajesh Kumar
- **Position**: Professor & Head of Department
- **Specialization**: Machine Learning, Data Science
- **Email**: rajesh.kumar@krmangalam.edu.in
- **Experience**: 15+ years in academia and industry

### Dr. Priya Sharma
- **Position**: Associate Professor
- **Specialization**: Cybersecurity, Network Systems
- **Email**: priya.sharma@krmangalam.edu.in
- **Experience**: 12 years

### Dr. Amit Verma
- **Position**: Assistant Professor
- **Specialization**: Artificial Intelligence, NLP
- **Email**: amit.verma@krmangalam.edu.in
- **Experience**: 8 years

## Mechanical Engineering Department

### Dr. Suresh Patel
- **Position**: Professor & Head of Department
- **Specialization**: Thermal Engineering, Manufacturing
- **Email**: suresh.patel@krmangalam.edu.in
- **Experience**: 20 years

### Dr. Anita Singh
- **Position**: Associate Professor
- **Specialization**: Robotics, Mechatronics
- **Email**: anita.singh@krmangalam.edu.in
- **Experience**: 10 years

## Civil Engineering Department

### Dr. Vikram Reddy
- **Position**: Professor & Head of Department
- **Specialization**: Structural Engineering
- **Email**: vikram.reddy@krmangalam.edu.in
- **Experience**: 18 years

## Electrical Engineering Department

### Dr. Meena Gupta
- **Position**: Professor & Head of Department
- **Specialization**: Power Systems, Renewable Energy
- **Email**: meena.gupta@krmangalam.edu.in
- **Experience**: 16 years
"""

# Sample syllabus information
SYLLABUS_DATA = """
# B.Tech Computer Science & Engineering - Curriculum Overview

## First Year (Common for all branches)

### Semester 1
- **Mathematics-I**: Calculus, Linear Algebra, Differential Equations
- **Physics**: Mechanics, Thermodynamics, Waves & Optics
- **Basic Electrical Engineering**: Circuit analysis, AC/DC fundamentals
- **Programming for Problem Solving (C)**: Variables, loops, functions, arrays
- **Engineering Graphics**: Technical drawing, AutoCAD basics
- **English Communication**: Technical writing, presentations

### Semester 2
- **Mathematics-II**: Probability, Statistics, Complex Analysis
- **Chemistry**: Organic, Inorganic, Physical Chemistry
- **Basic Electronics**: Semiconductors, Digital circuits
- **Workshop Practice**: Carpentry, Fitting, Welding
- **Environmental Science**: Ecology, Pollution control

## Second Year (CSE Specific)

### Semester 3
- **Data Structures**: Arrays, Linked Lists, Trees, Graphs, Hashing
- **Object-Oriented Programming (Java)**: Classes, Inheritance, Polymorphism
- **Digital Logic Design**: Boolean algebra, Combinational circuits
- **Discrete Mathematics**: Sets, Relations, Graph Theory
- **Computer Organization**: CPU architecture, Memory systems

### Semester 4
- **Operating Systems**: Process management, Memory management, File systems
- **Database Management Systems**: SQL, Normalization, Transactions
- **Design & Analysis of Algorithms**: Sorting, Searching, Dynamic Programming
- **Computer Networks**: OSI model, TCP/IP, Routing protocols
- **Software Engineering**: SDLC, Agile, Testing methodologies

## Third Year

### Semester 5
- **Artificial Intelligence**: Search algorithms, Knowledge representation
- **Machine Learning**: Supervised, Unsupervised, Neural Networks
- **Web Technologies**: HTML, CSS, JavaScript, React, Node.js
- **Cloud Computing**: AWS, Azure, Docker, Kubernetes
- **Elective-I**: Choose from IoT, Blockchain, AR/VR

### Semester 6
- **Deep Learning**: CNNs, RNNs, Transformers, GANs
- **Big Data Analytics**: Hadoop, Spark, Data pipelines
- **Cyber Security**: Cryptography, Network security, Ethical hacking
- **Minor Project**: Industry-relevant project work
- **Elective-II**: Choose from NLP, Computer Vision, Quantum Computing

## Fourth Year

### Semester 7
- **Compiler Design**: Lexical analysis, Parsing, Code generation
- **Distributed Systems**: CAP theorem, Consensus algorithms
- **Major Project - Part I**: Research-based project
- **Elective-III**: Advanced specialization
- **Industrial Training**: 6-week internship

### Semester 8
- **Major Project - Part II**: Project completion and presentation
- **Elective-IV**: Industry certification courses
- **Professional Ethics**: Engineering ethics, IPR
- **Entrepreneurship**: Startup ecosystem, Business planning

## Assessment Pattern
- **Continuous Assessment**: 40% (Assignments, Quizzes, Mid-terms)
- **End Semester Exam**: 60%
- **Practical/Lab**: Separate evaluation with viva
- **Projects**: Mentor evaluation + External jury

## Placement Support
- Pre-placement training from 5th semester
- Mock interviews and aptitude tests
- Industry guest lectures
- Internship opportunities with partner companies
"""

# Academic policies and SOPs
ACADEMIC_POLICIES = """
# SET Academic Policies & Procedures

## Attendance Policy
- Minimum 75% attendance required for exam eligibility
- Students with 65-74% attendance: Conditional permission with warning
- Below 65%: Detained, must repeat the semester
- Medical leave requires valid certificates submitted within 7 days

## Examination Rules
- Students must carry ID card to all exams
- No electronic devices allowed in exam halls
- Late entry: Up to 30 minutes allowed, no extra time
- Malpractice: Zero in that subject + disciplinary action

## Grading System
| Grade | Marks Range | Grade Points |
|-------|-------------|--------------|
| O     | 90-100      | 10           |
| A+    | 80-89       | 9            |
| A     | 70-79       | 8            |
| B+    | 60-69       | 7            |
| B     | 50-59       | 6            |
| C     | 40-49       | 5            |
| F     | Below 40    | 0            |

## Re-evaluation Process
1. Apply within 7 days of result declaration
2. Pay re-evaluation fee at accounts
3. Submit application to exam cell
4. Results within 15 working days

## Academic Integrity
- Plagiarism check mandatory for all submissions
- Maximum similarity index: 20%
- Violations result in grade penalty or course failure
- Repeat offenders face disciplinary committee review

## Leave Application
- Prior approval required for planned leave
- Emergency leave: Inform within 24 hours
- Maximum casual leave: 10 days per semester
- Submit applications through student portal

## Library Rules
- Timing: 8 AM to 10 PM (Monday-Saturday)
- Maximum 4 books for 14 days
- Fine: ₹5 per day per book for late return
- Reference books: In-library use only

## Computer Lab Guidelines
- Log in with university credentials only
- No food or drinks in labs
- Report hardware issues immediately
- Save work frequently, labs close at 8 PM

## Hostel Rules
- Entry deadline: 9 PM (weekdays), 10 PM (weekends)
- Visitor timing: 10 AM - 6 PM
- Report maintenance issues to warden
- Mess timings posted at hostel notice board
"""


class KnowledgeBaseSeeder:
    """Seed the knowledge base with SET institutional documents"""
    
    def __init__(self, store, rag_engine):
        self.store = store
        self.rag_engine = rag_engine
        self.processor = DocumentProcessor()

    def load_local_dataset(self) -> List[Dict]:
        """Load the curated local KRMU dataset if it exists."""
        if not LOCAL_DATASET_PATH.exists():
            logger.info("Local KRMU dataset not found at %s", LOCAL_DATASET_PATH)
            return []

        try:
            payload = json.loads(LOCAL_DATASET_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("Failed to load local KRMU dataset: %s", exc)
            return []

        documents = payload.get("documents", [])
        if not isinstance(documents, list):
            logger.error("Local KRMU dataset is malformed: 'documents' must be a list")
            return []

        logger.info("Loaded %s curated KRMU dataset documents", len(documents))
        return documents

    async def _create_seed_document(
        self,
        doc_id: str,
        title: str,
        description: str,
        doc_type: str,
        filename: str,
        file_size: int,
        category: str,
        metadata: Optional[Dict] = None,
    ) -> Dict:
        """Create a seed document record before indexing its chunks."""
        from datetime import datetime, timezone

        doc_record = {
            "id": doc_id,
            "title": title,
            "description": description,
            "doc_type": doc_type,
            "filename": filename,
            "file_size": file_size,
            "chunk_count": 0,
            "status": "processing",
            "uploaded_by": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "indexed_at": None,
            "is_seed": True,
            "category": category,
        }
        if metadata:
            doc_record.update(metadata)

        await self.store.create_document(doc_record)
        return doc_record
    
    async def seed_url(self, url_info: Dict) -> Dict:
        """Scrape and index a single URL"""
        url = url_info["url"]
        title = url_info["title"]
        category = url_info.get("category", "general")
        doc_id = None
        
        try:
            result = await self.processor.process_url(url)
            
            if not result["success"]:
                return {
                    "url": url,
                    "success": False,
                    "error": result.get("error", "Unknown error")
                }
            
            # Add to RAG engine
            import uuid
            doc_id = str(uuid.uuid4())
            from datetime import datetime, timezone

            await self._create_seed_document(
                doc_id=doc_id,
                title=title,
                description=f"Auto-seeded from {url}",
                doc_type="url",
                filename=url,
                file_size=len(result.get("text", "")),
                category=category,
                metadata={
                    "source_url": url,
                    "seed_origin": "official_url",
                },
            )

            chunk_count = self.rag_engine.add_document_chunks(
                document_id=doc_id,
                document_title=title,
                chunks=result["chunks"],
                metadata={"category": category, "source_url": url, "seed": True},
            )

            await self.store.update_document(
                doc_id,
                {
                    "status": "indexed",
                    "chunk_count": chunk_count,
                    "indexed_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            
            return {
                "url": url,
                "title": title,
                "success": True,
                "chunks": chunk_count
            }
            
        except Exception as e:
            logger.error(f"Error seeding URL {url}: {e}")
            if doc_id:
                await self.store.update_document(
                    doc_id,
                    {"status": "failed", "error_message": str(e)},
                )
            return {
                "url": url,
                "success": False,
                "error": str(e)
            }
    
    async def seed_text_document(
        self,
        title: str,
        content: str,
        category: str,
        metadata: Optional[Dict] = None,
        description: Optional[str] = None,
    ) -> Dict:
        """Seed a text-based document"""
        doc_id = None
        try:
            import uuid
            from datetime import datetime, timezone
            
            # Process text
            result = self.processor.process_txt(content.encode('utf-8'))
            
            if not result["success"]:
                return {"title": title, "success": False, "error": result.get("error")}
            
            doc_id = str(uuid.uuid4())
            chunk_metadata = {"category": category, "seed": True}
            if metadata:
                for key, value in metadata.items():
                    if isinstance(value, (str, int, float, bool)):
                        chunk_metadata[key] = value

            await self._create_seed_document(
                doc_id=doc_id,
                title=title,
                description=description or f"Knowledge base seed: {category}",
                doc_type="txt",
                filename=f"{title.lower().replace(' ', '_')}.txt",
                file_size=len(content.encode("utf-8")),
                category=category,
                metadata=metadata,
            )

            chunk_count = self.rag_engine.add_document_chunks(
                document_id=doc_id,
                document_title=title,
                chunks=result["chunks"],
                metadata=chunk_metadata,
            )

            await self.store.update_document(
                doc_id,
                {
                    "status": "indexed",
                    "chunk_count": chunk_count,
                    "indexed_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            
            return {
                "title": title,
                "success": True,
                "chunks": chunk_count
            }
            
        except Exception as e:
            logger.error(f"Error seeding document {title}: {e}")
            if doc_id:
                await self.store.update_document(
                    doc_id,
                    {"status": "failed", "error_message": str(e)},
                )
            return {"title": title, "success": False, "error": str(e)}

    async def seed_dataset_document(self, record: Dict) -> Dict:
        """Seed a single curated dataset document."""
        title = record.get("title") or "Untitled KRMU Document"
        content = record.get("content") or ""
        category = record.get("category") or "general"
        source_url = record.get("source_url")
        verified_on = record.get("verified_on")
        description = (
            f"Curated official KRMU dataset entry"
            + (f" from {source_url}" if source_url else "")
        )

        metadata = {
            "seed_origin": "official_dataset",
            "source_url": source_url or "",
            "verified_on": verified_on or "",
        }

        result = await self.seed_text_document(
            title=title,
            content=content,
            category=category,
            metadata=metadata,
            description=description,
        )
        if result.get("success"):
            result["source_url"] = source_url
            result["verified_on"] = verified_on
        return result
    
    async def seed_all(self) -> Dict:
        """Seed all knowledge base documents"""
        results = {
            "urls": [],
            "documents": [],
            "total_chunks": 0,
            "success_count": 0,
            "error_count": 0
        }
        
        # Check if already seeded
        existing_seeds = await self.store.count_documents({"is_seed": True})
        if existing_seeds > 0:
            logger.info(f"Knowledge base already seeded with {existing_seeds} documents")
            return {
                "message": "Knowledge base already seeded",
                "existing_documents": existing_seeds
            }

        dataset_documents = self.load_local_dataset()
        if dataset_documents:
            logger.info("Seeding curated local KRMU dataset...")
            for record in dataset_documents:
                result = await self.seed_dataset_document(record)
                results["documents"].append(result)
                if result["success"]:
                    results["success_count"] += 1
                    results["total_chunks"] += result.get("chunks", 0)
                else:
                    results["error_count"] += 1

            logger.info(
                "Local dataset seeding complete: %s successful, %s failed, %s total chunks",
                results["success_count"],
                results["error_count"],
                results["total_chunks"]
            )
            return results
        
        # Seed URLs
        logger.info(f"Seeding {len(SEED_URLS)} URLs...")
        for url_info in SEED_URLS:
            result = await self.seed_url(url_info)
            results["urls"].append(result)
            if result["success"]:
                results["success_count"] += 1
                results["total_chunks"] += result.get("chunks", 0)
            else:
                results["error_count"] += 1
        
        # Seed faculty data
        logger.info("Seeding faculty directory...")
        faculty_result = await self.seed_text_document(
            "SET Faculty Directory",
            FACULTY_DATA,
            "faculty"
        )
        results["documents"].append(faculty_result)
        if faculty_result["success"]:
            results["success_count"] += 1
            results["total_chunks"] += faculty_result.get("chunks", 0)
        else:
            results["error_count"] += 1
        
        # Seed syllabus
        logger.info("Seeding curriculum data...")
        syllabus_result = await self.seed_text_document(
            "B.Tech CSE Curriculum & Syllabus",
            SYLLABUS_DATA,
            "syllabus"
        )
        results["documents"].append(syllabus_result)
        if syllabus_result["success"]:
            results["success_count"] += 1
            results["total_chunks"] += syllabus_result.get("chunks", 0)
        else:
            results["error_count"] += 1
        
        # Seed academic policies
        logger.info("Seeding academic policies...")
        policies_result = await self.seed_text_document(
            "SET Academic Policies & Procedures",
            ACADEMIC_POLICIES,
            "policies"
        )
        results["documents"].append(policies_result)
        if policies_result["success"]:
            results["success_count"] += 1
            results["total_chunks"] += policies_result.get("chunks", 0)
        else:
            results["error_count"] += 1
        
        logger.info(f"Seeding complete: {results['success_count']} successful, {results['error_count']} failed, {results['total_chunks']} total chunks")
        
        return results
    
    async def clear_seeds(self) -> Dict:
        """Clear all seeded documents"""
        try:
            # Get all seed document IDs
            seed_docs = [
                {"id": doc["id"]}
                for doc in await self.store.list_documents(limit=500)
                if doc.get("is_seed")
            ]
            
            deleted_count = 0
            for doc in seed_docs:
                self.rag_engine.delete_document(doc["id"])
                deleted_count += 1
            
            # Remove from database
            deleted_documents = 0
            for doc in seed_docs:
                if await self.store.delete_document(doc["id"]):
                    deleted_documents += 1
            
            return {
                "success": True,
                "deleted_documents": deleted_documents,
                "deleted_chunks": deleted_count
            }
            
        except Exception as e:
            logger.error(f"Error clearing seeds: {e}")
            return {"success": False, "error": str(e)}
