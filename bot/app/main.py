from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Form, Cookie, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from database.db_connector import db
import uuid
import json
from typing import Optional

app = FastAPI(title="ShopEZ Laptops AI Assistant", version="1.0.0")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Initialize dialogue manager
from services.dialogue_manager import DialogueManager
dialogue_manager = DialogueManager()

# Clean up expired sessions on startup
try:
    db.cleanup_expired_sessions()
    print("Expired sessions cleaned up successfully.")
except Exception as e:
    print(f"Error cleaning up sessions: {e}")
    print("This is normal during first run or schema changes.")

def get_current_user(request: Request):
    """Get current user from session"""
    session_token = request.cookies.get("session_token")
    
    if session_token:
        # Verify session is valid
        user = db.validate_session(session_token)
        if user:
            return user
    return None

@app.get("/", response_class=HTMLResponse)
async def home_page(request: Request):
    """Home page - redirect to login or chat"""
    user = get_current_user(request)
    if user:
        return RedirectResponse(url="/chat")
    return RedirectResponse(url="/login")

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: Optional[str] = None, message: Optional[str] = None):
    """Login page"""
    user = get_current_user(request)
    if user:
        return RedirectResponse(url="/chat")
    
    return templates.TemplateResponse("login.html", {
        "request": request,
        "error": error,
        "message": message
    })

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, error: Optional[str] = None):
    """Registration page"""
    user = get_current_user(request)
    if user:
        return RedirectResponse(url="/chat")
    
    return templates.TemplateResponse("register.html", {
        "request": request,
        "error": error
    })

@app.post("/register")
async def register_user(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    first_name: str = Form(""),
    last_name: str = Form("")
):
    """Handle user registration - redirect to login after registration"""
    try:
        user_data = {
            "username": username,
            "email": email,
            "password": password,
            "first_name": first_name,
            "last_name": last_name
        }
        
        user = db.register_user(user_data)
        
        # Instead of auto-login, redirect to login page with success message
        response = RedirectResponse(url="/login?message=Registration successful! Please login.", status_code=303)
        return response
        
    except ValueError as e:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": str(e),
            "form_data": {
                "username": username,
                "email": email,
                "first_name": first_name,
                "last_name": last_name
            }
        })

@app.post("/login")
async def login_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...)
):
    """Handle user login"""
    user = db.authenticate_user(username, password)
    
    if user:
        # Create session
        session_token = str(uuid.uuid4())
        db.create_session(user["user_id"], session_token)
        
        # Create response with cookies - FIXED for JavaScript access
        response = RedirectResponse(url="/chat", status_code=303)
        
        # Set cookies with proper settings for JavaScript access
        response.set_cookie(
            key="session_token", 
            value=session_token, 
            httponly=False,  # Changed to allow JavaScript access
            max_age=24*60*60,
            samesite="lax",
            path="/",
            secure=False,
            domain=None  # Explicitly set to None for current domain
        )
        response.set_cookie(
            key="user_id", 
            value=user["user_id"],
            max_age=24*60*60,
            httponly=False,  # Changed to allow JavaScript access
            path="/",
            secure=False,
            domain=None
        )
        response.set_cookie(
            key="username", 
            value=user["username"],
            max_age=24*60*60,
            httponly=False,  # Changed to allow JavaScript access
            path="/",
            secure=False,
            domain=None
        )
        
        print(f"Login successful for {username}. Cookies set with domain=None, path=/")
        return response
    
    return templates.TemplateResponse("login.html", {
        "request": request,
        "error": "Invalid username or password",
        "username": username
    })
@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    """Chat interface - requires authentication"""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")
    
    return templates.TemplateResponse("index.html", {
        "request": request,
        "user": user
    })

@app.get("/logout")
async def logout(request: Request, response: Response):
    """Logout user"""
    session_token = request.cookies.get("session_token")
    if session_token:
        db.delete_session(session_token)
    
    response = RedirectResponse(url="/login")
    response.delete_cookie("session_token")
    response.delete_cookie("user_id")
    response.delete_cookie("username")
    return response

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    session_id = str(uuid.uuid4())
    
    try:
        # Get session token from query parameters
        query_params = dict(websocket.query_params)
        session_token = query_params.get('session_token')
        
        print(f"WebSocket connection attempt - Session token: {session_token}")
        
        if not session_token:
            error_msg = "Authentication required. No session token provided."
            print(error_msg)
            await websocket.send_json({
                "response": "Please refresh the page and login again.",
                "buttons": []
            })
            await websocket.close(code=1008, reason="Authentication required")
            return
        
        # Validate session
        user = db.validate_session(session_token)
        if not user:
            error_msg = f"Invalid session token: {session_token}"
            print(error_msg)
            await websocket.send_json({
                "response": "Session expired. Please refresh the page and login again.",
                "buttons": []
            })
            await websocket.close(code=1008, reason="Invalid session")
            return
        
        print(f"WebSocket authenticated for user: {user['username']} (ID: {user['user_id']})")
        
        welcome_msg = {
            "response": f"Hello {user['first_name'] or user['username']}! Welcome to ShopEZ Laptops. How can I help you today?",
            "buttons": ["Purchase Laptop", "Order Status", "Return/Cancel", "Warranty"],
            "session_id": session_id
        }
        await websocket.send_json(welcome_msg)
        
        # Initialize fresh session context
        db.update_user_session(user['user_id'], session_id, "{}", json.dumps({"user_data": user}))
        
        while True:
            data = await websocket.receive_json()
            message_type = data.get('type')
            user_message = data.get('content', '').strip()
            
            if message_type == 'message' and user_message:
                # Get fresh session context for each message to prevent sticking
                session_data = db.get_user_session(session_id)
                if session_data:
                    context = json.loads(session_data.get('context', '{}'))
                else:
                    context = {"user_data": user}
                
                response = dialogue_manager.handle_message(user_message, user, session_id, context)
                await websocket.send_json(response)
                
                # Update session with fresh context
                db.update_user_session(user['user_id'], session_id, 
                                     json.dumps(dialogue_manager.current_state),
                                     json.dumps(dialogue_manager.context))
                
                if response.get('escalated'):
                    break
                    
    except WebSocketDisconnect:
        print(f"Client disconnected from session {session_id}")
    except Exception as e:
        print(f"WebSocket error: {e}")
        error_response = {
            "response": "I apologize, I'm experiencing technical difficulties. Please try again later.",
            "buttons": ["Purchase Laptop", "Order Status", "Return/Cancel", "Warranty"]
        }
        try:
            await websocket.send_json(error_response)
        except:
            pass  # Connection already closed # Connection already closed

@app.get("/api/conversations")
async def get_conversations(request: Request):
    """Get user conversations"""
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Authentication required"}, status_code=401)
    
    conversations = db.get_user_conversations(user["user_id"], 20)
    return JSONResponse({"conversations": conversations})

@app.get("/api/transactions")
async def get_transactions(request: Request):
    """Get user transactions"""
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Authentication required"}, status_code=401)
    
    transactions = dialogue_manager.transaction_service.get_transaction_history(user["user_id"])
    return JSONResponse(transactions)

@app.get("/debug/cookies")
async def debug_cookies(request: Request):
    """Debug endpoint to check cookies"""
    cookies = {
        "session_token": request.cookies.get("session_token"),
        "user_id": request.cookies.get("user_id"),
        "username": request.cookies.get("username")
    }
    return JSONResponse({"cookies": cookies})

@app.get("/debug/session")
async def debug_session(request: Request):
    """Debug endpoint to check session validation"""
    session_token = request.cookies.get("session_token")
    if not session_token:
        return JSONResponse({"error": "No session token"})
    
    user = db.validate_session(session_token)
    return JSONResponse({
        "session_token": session_token,
        "valid": user is not None,
        "user": user
    })

@app.get("/api/health")
async def health_check():
    return JSONResponse({"status": "healthy", "service": "ShopEZ Laptops AI Assistant"})

@app.get("/debug/session-status")
async def debug_session_status(request: Request):
    """Debug endpoint to check session status"""
    session_token = request.cookies.get("session_token")
    user_id = request.cookies.get("user_id")
    username = request.cookies.get("username")
    
    session_valid = False
    user = None
    
    if session_token:
        user = db.validate_session(session_token)
        session_valid = user is not None
    
    return JSONResponse({
        "cookies_present": {
            "session_token": session_token is not None,
            "user_id": user_id is not None,
            "username": username is not None
        },
        "session_valid": session_valid,
        "user": user,
        "session_token": session_token
    })

@app.get("/test-cookies")
async def test_cookies(request: Request, response: Response):
    """Test endpoint to set and check cookies"""
    # Set a test cookie that JavaScript can definitely read
    response = JSONResponse({
        "message": "Test cookies set",
        "server_cookies": dict(request.cookies)
    })
    
    response.set_cookie(
        key="js_test_cookie",
        value="javascript_accessible",
        max_age=60,
        path="/",
        httponly=False,  # Must be false for JS access
        secure=False,
        domain=None,
        samesite="lax"
    )
    
    return response

@app.get("/debug/check-cookie")
async def debug_check_cookie(request: Request):
    """Check if cookies are accessible"""
    cookies = {
        "session_token": request.cookies.get("session_token"),
        "user_id": request.cookies.get("user_id"),
        "username": request.cookies.get("username"),
        "test_cookie": request.cookies.get("test_cookie")
    }
    return JSONResponse({"cookies_received": cookies})

@app.get("/debug/pinecone-test")
async def debug_pinecone_test(request: Request):
    """Test Pinecone connection and data structure"""
    try:
        # Test with a simple query
        results = dialogue_manager.product_manager.search_products(
            query="laptop",
            top_k=5,
            max_price=None
        )
        
        sample_products = []
        if results and results.get('matches'):
            for i, match in enumerate(results['matches'][:3]):
                product = match['metadata']
                sample_products.append({
                    'id': match['id'],
                    'score': match['score'],
                    'name': product.get('name') or product.get('product_name', 'N/A'),
                    'price': product.get('price', 'N/A'),
                    'brand': product.get('brand', 'N/A'),
                    'rating': product.get('rating', 'N/A'),
                    'fields_available': list(product.keys())
                })
        
        return JSONResponse({
            "pinecone_connected": True,
            "total_matches": len(results['matches']) if results else 0,
            "sample_products": sample_products
        })
        
    except Exception as e:
        return JSONResponse({"pinecone_connected": False, "error": str(e)})
    
if __name__ == "__main__":
    import uvicorn
    from config import Config
    uvicorn.run(app, host=Config.HOST, port=Config.PORT)