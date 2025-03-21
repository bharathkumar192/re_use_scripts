import json
import time
import os
import sys
import random
import logging
import argparse
import signal
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import List, Dict, Any, Optional, Set
import requests

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("gemini_processor.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

shutdown_requested = False
processing_lock = threading.Lock()
QUESTION_PROMPT = ''' Before giving the output ,
1- read through all the instructions i have given you , 
2 - prepare a checklist of what you have to deliverand
 3- make sure you are passing thorough all of them

4-You won't need to write all the words in Telugu, You are free to use words which are English but written in Telugu(for example - సక్సెస్, ట్రస్ట్ like this) And make sure to keep the answer casual and very informational , use new telugu instrctions.

5- Go through all the words you are going to use and context where you gonna use them , plan it all
6- then decide the whole information you wat to write  - A 10 point plan of what information should output have and very information rich'''
        


class KeyManager:
    def __init__(self, api_keys: List[str], rpm_limit: int = 9, daily_limit: int = 1450):
        self.rpm_limit = rpm_limit
        self.daily_limit = daily_limit
        self.keys = []
        self.lock = threading.Lock()
        
        for key in api_keys:
            key = key.strip()
            if key:  # Skip empty lines
                self.keys.append({
                    'key': key,
                    'requests_this_minute': 0,
                    'requests_today': 0,
                    'last_request_time': 0,
                    'minute_reset_time': time.time(),
                    'daily_reset_time': time.time(),
                    'is_available': True,
                    'consecutive_errors': 0
                })
        
        logger.info(f"Initialized {len(self.keys)} API keys")
    
    def get_next_key(self) -> Optional[Dict[str, Any]]:
        with self.lock:
            now = time.time()
            
            for key_data in self.keys:
                if now - key_data['minute_reset_time'] >= 60:
                    key_data['requests_this_minute'] = 0
                    key_data['minute_reset_time'] = now
                
                if now - key_data['daily_reset_time'] >= 24 * 60 * 60:
                    key_data['requests_today'] = 0
                    key_data['daily_reset_time'] = now
            
            available_keys = [
                k for k in self.keys 
                if k['is_available'] and 
                k['requests_this_minute'] < self.rpm_limit and
                k['requests_today'] < self.daily_limit and
                k['consecutive_errors'] < 3 and
                (now - k['last_request_time']) >= 0.1
            ]
            
            if not available_keys:
                return None
            
            key_data = random.choice(available_keys)
            
            key_data['requests_this_minute'] += 1
            key_data['requests_today'] += 1
            key_data['last_request_time'] = now
            
            return key_data
    
    def mark_error(self, key: str) -> None:
        with self.lock:
            for key_data in self.keys:
                if key_data['key'] == key:
                    key_data['consecutive_errors'] += 1
                    
                    if key_data['consecutive_errors'] >= 3:
                        key_data['is_available'] = False
                        
                        def reenable_key():
                            with self.lock:
                                for k in self.keys:
                                    if k['key'] == key:
                                        k['is_available'] = True
                                        k['consecutive_errors'] = 0
                                        logger.info(f"Re-enabled API key after cool-down: {key[:8]}...")
                        
                        timer = threading.Timer(5 * 60, reenable_key)
                        timer.daemon = True
                        timer.start()
                    break
    
    def mark_success(self, key: str) -> None:
        with self.lock:
            for key_data in self.keys:
                if key_data['key'] == key:
                    key_data['consecutive_errors'] = 0
                    break
    
    def get_stats(self) -> Dict[str, Any]:
        with self.lock:
            total_requests = sum(k['requests_today'] for k in self.keys)
            available_keys = sum(1 for k in self.keys if k['is_available'])
            
            return {
                'total_keys': len(self.keys),
                'available_keys': available_keys,
                'total_requests_today': total_requests,
                'estimated_remaining_capacity': (len(self.keys) * self.daily_limit) - total_requests
            }


class GeminiProcessor:
    def __init__(
        self, 
        api_keys: List[str], 
        system_prompt_file: str,
        output_file: str = "results.json",
        checkpoint_dir: str = "checkpoints",
        concurrency: int = 5,
        max_retries: int = 5,
        save_sample_request: bool = False
    ):
        self.key_manager = KeyManager(api_keys)
        self.system_prompt = self._read_system_prompt(system_prompt_file)
        self.output_file = output_file
        self.checkpoint_dir = checkpoint_dir
        self.concurrency = concurrency
        self.max_retries = max_retries
        self.api_url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
        self.save_sample_request = save_sample_request
        self.sample_saved = False
        
        self.is_processing = False
        self.processed_count = 0
        self.total_count = 0
        self.results = []
        self.current_index = 0
        self.start_time = None
        self.error_count = 0
        self.success_count = 0
        
        if not os.path.exists(checkpoint_dir):
            os.makedirs(checkpoint_dir)
    
    def _read_system_prompt(self, system_prompt_file: str) -> str:
        try:
            with open(system_prompt_file, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            logger.error(f"Error reading system prompt file: {e}")
            return ""
    
    def _save_sample_request(self, question: str, api_key: str) -> None:
        if self.save_sample_request and not self.sample_saved:
            try:
                data = {
                    "contents": {
                        "parts": [
                            {
                                "text": f' Answer this Question: "{question}" \n {QUESTION_PROMPT}',
                            },
                        ],
                    },
                    "system_instruction": {
                        "parts": [
                            {
                                "text": self.system_prompt,
                            },
                        ],
                    },
                }
                
                with open("sample_request.txt", "w", encoding="utf-8") as f:
                    f.write(f"URL: {self.api_url}?key=YOUR_API_KEY_HERE\n\n")
                    f.write("Headers:\n")
                    f.write("Content-Type: application/json\n\n")
                    f.write("Request Body:\n")
                    f.write(json.dumps(data, indent=2, ensure_ascii=False))
                
                logger.info("Sample request saved to sample_request.txt")
                self.sample_saved = True
            except Exception as e:
                logger.error(f"Error saving sample request: {e}")
    
    async def make_gemini_request(self, question: str, api_key: str) -> str:
        try:
            # Save sample request if needed
            self._save_sample_request(question, api_key)
            
            data = {
                "contents": {
                    "parts": [
                        {
                            "text": f'use new telugu and write this question into telugu and keep it casually asking 2025 words, make it look like you are asking another person, Question: "{question}"',
                        },
                    ],
                },
                "system_instruction": {
                    "parts": [
                        {
                            "text": self.system_prompt,
                        },
                    ],
                },
            }
            
            url = f"{self.api_url}?key={api_key}"
            headers = {"Content-Type": "application/json"}
            
            response = requests.post(url, headers=headers, json=data)
            response.raise_for_status()
            
            response_data = response.json()
            
            if response_data.get("candidates") and response_data["candidates"][0].get("content") and response_data["candidates"][0]["content"].get("parts"):
                self.key_manager.mark_success(api_key)
                return response_data["candidates"][0]["content"]["parts"][0]["text"]
            
            return "ERROR: Unexpected response format"
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if hasattr(e, 'response') else None
            self.key_manager.mark_error(api_key)
            logger.error(f"HTTP error with key {api_key[:8]}...: {e} (Status: {status_code})")
            return f"ERROR: HTTP error {status_code}" if status_code else f"ERROR: {str(e)}"
        except Exception as e:
            self.key_manager.mark_error(api_key)
            logger.error(f"Error making request with key {api_key[:8]}...: {e}")
            return f"ERROR: {str(e)}"
    
    async def make_gemini_request_with_retry(self, question: str) -> str:
        retry_count = 0
        
        while retry_count < self.max_retries:
            key_data = None
            
            while not key_data and retry_count < self.max_retries:
                key_data = self.key_manager.get_next_key()
                
                if not key_data:
                    wait_time = min(1000 * (2 ** retry_count), 30000) / 1000.0
                    logger.info(f"No keys available. Waiting {wait_time:.2f}s before retry...")
                    time.sleep(wait_time)
                    retry_count += 1
            
            if not key_data:
                return "ERROR: No API keys available after retries"
            
            try:
                result = await self.make_gemini_request(question, key_data['key'])
                
                if "429" in result:
                    retry_count += 1
                    backoff_time = min(1000 * (2 ** retry_count), 30000) / 1000.0
                    logger.info(f"Rate limit hit. Retrying in {backoff_time:.2f}s (attempt {retry_count}/{self.max_retries})")
                    time.sleep(backoff_time)
                elif result.startswith("ERROR:"):
                    retry_count += 1
                    backoff_time = min(1000 * (2 ** retry_count), 30000) / 1000.0
                    logger.info(f"Error: {result}. Retrying in {backoff_time:.2f}s (attempt {retry_count}/{self.max_retries})")
                    time.sleep(backoff_time)
                else:
                    return result
            except Exception as e:
                retry_count += 1
                backoff_time = min(1000 * (2 ** retry_count), 30000) / 1000.0
                logger.error(f"Unexpected error: {e}. Retrying in {backoff_time:.2f}s (attempt {retry_count}/{self.max_retries})")
                time.sleep(backoff_time)
        
        return "ERROR: Maximum retries exceeded"
    
    def process_question(self, question: str) -> Dict[str, str]:
        if shutdown_requested:
            return {"question": question, "response": "ERROR: Processing interrupted"}
        
        try:
            logger.info(f"Processing question: {question[:50]}...")
            
            response = asyncio.run(self.make_gemini_request_with_retry(question))
            
            if response.startswith("ERROR:"):
                with processing_lock:
                    self.error_count += 1
            else:
                with processing_lock:
                    self.success_count += 1
            
            return {"question": question, "response": response}
        except Exception as e:
            logger.error(f"Failed to process question: {e}")
            with processing_lock:
                self.error_count += 1
            return {"question": question, "response": f"ERROR: {str(e)}"}
    
    def process_questions(self, questions: List[str]) -> None:
        if self.is_processing:
            logger.warning("Processing already in progress")
            return
        
        try:
            with processing_lock:
                self.total_count = len(questions)
                self.processed_count = 0
                self.current_index = 0
                self.is_processing = True
                self.start_time = time.time()
                self.results = []
                self.error_count = 0
                self.success_count = 0
            
            logger.info(f"Processing {self.total_count} questions with {self.key_manager.get_stats()['total_keys']} API keys")
            logger.info(f"Using concurrency limit of {self.concurrency}")
            
            with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
                future_to_question = {executor.submit(self.process_question, q): q for q in questions}
                
                for i, future in enumerate(concurrent.futures.as_completed(future_to_question)):
                    if shutdown_requested:
                        logger.info("Shutdown requested, stopping processing...")
                        executor.shutdown(wait=False)
                        break
                    
                    try:
                        result = future.result()
                        with processing_lock:
                            self.results.append(result)
                            self.processed_count += 1
                        
                        if self.processed_count % 10 == 0 or self.processed_count == self.total_count:
                            elapsed = time.time() - self.start_time
                            rate = self.processed_count / elapsed if elapsed > 0 else 0
                            logger.info(f"Processed {self.processed_count}/{self.total_count} questions ({rate:.2f}/sec)")
                        
                        if self.processed_count % 10 == 0:
                            self.save_checkpoint()
                        
                        self.save_results()
                    except Exception as e:
                        logger.error(f"Error processing question result: {e}")
            
            logger.info(f"Processing completed: {self.success_count} successful, {self.error_count} errors")
            
            self.save_results()
            self.save_checkpoint(label="final")
            
            with processing_lock:
                self.is_processing = False
        except Exception as e:
            logger.error(f"Error in process_questions: {e}")
            with processing_lock:
                self.is_processing = False
    
    def save_checkpoint(self, label: str = "") -> None:
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            checkpoint_file = f"checkpoint_{label + '_' if label else ''}{timestamp}.json"
            checkpoint_path = os.path.join(self.checkpoint_dir, checkpoint_file)
            
            with processing_lock:
                checkpoint_data = {
                    "timestamp": timestamp,
                    "processed_count": self.processed_count,
                    "total_count": self.total_count,
                    "success_count": self.success_count,
                    "error_count": self.error_count,
                    "elapsed_time": time.time() - self.start_time if self.start_time else 0,
                    "key_stats": self.key_manager.get_stats(),
                    "results": self.results
                }
            
            with open(checkpoint_path, 'w', encoding='utf-8') as f:
                json.dump(checkpoint_data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Checkpoint saved: {checkpoint_path}")
        except Exception as e:
            logger.error(f"Error saving checkpoint: {e}")
    
    def save_results(self) -> None:
        try:
            with processing_lock:
                with open(self.output_file, 'w', encoding='utf-8') as f:
                    json.dump({"questions": self.results}, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error saving results: {e}")
    
    def get_progress(self) -> Dict[str, Any]:
        with processing_lock:
            if not self.is_processing and self.processed_count == 0:
                return {"status": "idle"}
            
            elapsed = time.time() - self.start_time if self.start_time else 0
            remaining = self.total_count - self.processed_count
            rate = self.processed_count / elapsed if elapsed > 0 and self.processed_count > 0 else 0
            estimated_remaining = remaining / rate if rate > 0 else 0
            
            return {
                "status": "completed" if self.processed_count == self.total_count else "processing",
                "progress": {
                    "total": self.total_count,
                    "processed": self.processed_count,
                    "successful": self.success_count,
                    "errors": self.error_count,
                    "percentage": f"{(self.processed_count / self.total_count * 100):.2f}%" if self.total_count > 0 else "0%",
                },
                "performance": {
                    "elapsed_time": self._format_time(elapsed),
                    "estimated_remaining": self._format_time(estimated_remaining),
                    "questions_per_second": f"{rate:.2f}",
                    "api_keys": self.key_manager.get_stats(),
                }
            }
    
    def _format_time(self, seconds: float) -> str:
        if seconds < 0 or not seconds:
            return "0s"
        
        hours, remainder = divmod(int(seconds), 3600)
        minutes, seconds = divmod(remainder, 60)
        
        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        else:
            return f"{seconds}s"
    
    def resume_from_checkpoint(self, checkpoint_file: str) -> None:
        if self.is_processing:
            logger.warning("Cannot resume, processing already in progress")
            return
        
        try:
            checkpoint_path = os.path.join(self.checkpoint_dir, checkpoint_file)
            if not os.path.exists(checkpoint_path):
                logger.error(f"Checkpoint file not found: {checkpoint_file}")
                return
            
            with open(checkpoint_path, 'r', encoding='utf-8') as f:
                checkpoint_data = json.load(f)
            
            with processing_lock:
                self.results = checkpoint_data.get("results", [])
            
            processed_questions = set(r["question"] for r in self.results)
            
            with open("english_questions.json", 'r', encoding='utf-8') as f:
                questions_data = json.load(f)
            
            if not questions_data.get("questions") or not isinstance(questions_data["questions"], list):
                logger.error("Invalid questions format in file")
                return
            
            remaining_questions = [q for q in questions_data["questions"] if q not in processed_questions]
            
            logger.info(f"Resuming processing with {len(remaining_questions)} remaining questions")
            logger.info(f"Loaded {len(self.results)} previously processed results")
            
            self.process_questions(remaining_questions)
        except Exception as e:
            logger.error(f"Error resuming from checkpoint: {e}")


def handle_shutdown(signum, frame):
    global shutdown_requested
    if not shutdown_requested:
        logger.info("Shutdown requested. Finishing current processing and saving progress...")
        shutdown_requested = True


def load_api_keys_from_txt(filename: str) -> List[str]:
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            keys = [line.strip() for line in f if line.strip()]
        logger.info(f"Loaded {len(keys)} API keys from {filename}")
        return keys
    except Exception as e:
        logger.error(f"Error loading API keys from {filename}: {e}")
        return []


def main():
    parser = argparse.ArgumentParser(description="Process questions through Gemini API using multiple API keys")
    parser.add_argument("--input", default="english_questions.json", help="Input JSON file containing questions")
    parser.add_argument("--output", default="results.json", help="Output JSON file for results")
    parser.add_argument("--api-keys", default="api_keys.txt", help="Text file containing API keys (one per line)")
    parser.add_argument("--system-prompt", default="telugu_prompt.txt", help="File containing system prompt")
    parser.add_argument("--concurrency", type=int, default=5, help="Number of concurrent requests")
    parser.add_argument("--checkpoint-dir", default="checkpoints", help="Directory for checkpoints")
    parser.add_argument("--resume", help="Resume from checkpoint file")
    parser.add_argument("--sample-only", action="store_true", 
                    help="Save a sample request and exit without processing questions")
    parser.add_argument("--save-sample", action="store_true", help="Save a sample request to sample_request.txt")
    parser.add_argument("--test-one", action="store_true", 
                help="Process just one question and exit")
    parser.add_argument("--question-index", type=int, default=0,
                    help="Index of the question to process in test mode (default: 0)")
    parser.add_argument("--api-key-index", type=int, default=0,
                    help="Index of the API key to use in test mode (default: 0)")

    
    args = parser.parse_args()
    
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)
    
    try:
        # Load API keys from text file
        api_keys = load_api_keys_from_txt(args.api_keys)
        if not api_keys:
            logger.error("No API keys found in the specified file")
            return 1
        
        # Handle sample-only mode
        if args.sample_only:
            logger.info("Sample-only mode: Creating sample request and exiting")
            with open(args.input, 'r', encoding='utf-8') as f:
                questions_data = json.load(f)
                if questions_data.get("questions") and len(questions_data["questions"]) > 0:
                    # Create a temporary processor just to save the sample
                    sample_processor = GeminiProcessor(
                        api_keys=api_keys[:1],  # Just need one key for the sample
                        system_prompt_file=args.system_prompt,
                        output_file=args.output,
                        checkpoint_dir=args.checkpoint_dir,
                        save_sample_request=True
                    )
                    sample_question = questions_data["questions"][0]
                    # Save the sample without making an actual API call
                    sample_processor._save_sample_request(sample_question, "SAMPLE_API_KEY")
                    logger.info("Sample request saved to sample_request.txt. Exiting as requested.")
                    return 0
                else:
                    logger.error("No questions found to create sample request")
                    return 1
        

        if args.test_one:
            logger.info("Test-one mode: Processing a single question")
            with open(args.input, 'r', encoding='utf-8') as f:
                questions_data = json.load(f)
                if not questions_data.get("questions") or not isinstance(questions_data["questions"], list):
                    logger.error("Invalid questions format in input file")
                    return 1
                    
                # Make sure the index is valid
                if args.question_index < 0 or args.question_index >= len(questions_data["questions"]):
                    logger.error(f"Question index {args.question_index} out of range (0-{len(questions_data['questions'])-1})")
                    return 1
                    
                # Make sure we have at least one API key
                if args.api_key_index < 0 or args.api_key_index >= len(api_keys):
                    logger.error(f"API key index {args.api_key_index} out of range (0-{len(api_keys)-1})")
                    return 1
                    
                # Get the selected question and API key
                selected_question = questions_data["questions"][args.question_index]
                selected_api_key = api_keys[args.api_key_index]
                
                logger.info(f"Testing with question {args.question_index}: {selected_question}")
                logger.info(f"Using API key index {args.api_key_index}: {selected_api_key[:8]}...")
                
                # Create a temporary processor
                test_processor = GeminiProcessor(
                    api_keys=[selected_api_key],  # Just use one key
                    system_prompt_file=args.system_prompt,
                    output_file=args.output,
                    save_sample_request=args.save_sample
                )
                
                # Process the single question
                try:
                    logger.info("Sending request to Gemini API...")
                    response = asyncio.run(test_processor.make_gemini_request(selected_question, selected_api_key))
                    
                    logger.info("Response received:")
                    logger.info("-" * 40)
                    logger.info(response)
                    logger.info("-" * 40)
                    
                    # Save to a simple result file
                    with open("test_result.json", "w", encoding="utf-8") as f:
                        json.dump({
                            "question": selected_question,
                            "response": response,
                            "api_key": selected_api_key[:8] + "..."  # Truncate for safety
                        }, f, indent=2, ensure_ascii=False)
                    
                    logger.info("Result saved to test_result.json")
                    return 0
                    
                except Exception as e:
                    logger.error(f"Error processing test question: {e}")
                    return 1
        
        # Normal processing mode
        processor = GeminiProcessor(
            api_keys=api_keys,
            system_prompt_file=args.system_prompt,
            output_file=args.output,
            checkpoint_dir=args.checkpoint_dir,
            concurrency=args.concurrency,
            save_sample_request=args.save_sample
        )
        
        if args.resume:
            processor.resume_from_checkpoint(args.resume)
        else:
            with open(args.input, 'r', encoding='utf-8') as f:
                questions_data = json.load(f)
                if not questions_data.get("questions") or not isinstance(questions_data["questions"], list):
                    logger.error("Invalid questions format in input file")
                    return 1
                
                processor.process_questions(questions_data["questions"])
        
        progress = processor.get_progress()
        logger.info("Processing completed!")
        logger.info(f"Total questions: {progress['progress']['total']}")
        logger.info(f"Processed: {progress['progress']['processed']}")
        logger.info(f"Successful: {progress['progress'].get('successful', 0)}")
        logger.info(f"Errors: {progress['progress'].get('errors', 0)}")
        logger.info(f"Total time: {progress['performance']['elapsed_time']}")
        
        return 0
    except KeyboardInterrupt:
        logger.info("Process interrupted by user")
        return 1
    except Exception as e:
        logger.error(f"Error in main: {e}")
        return 1


if __name__ == "__main__":
    import asyncio
    import concurrent.futures
    sys.exit(main())