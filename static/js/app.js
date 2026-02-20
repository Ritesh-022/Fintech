// FinTech Intelligence Platform - Main JavaScript
// AI Assistant and Interactive Features

class AIAssistant {
    constructor() {
        // Remove this class - using chatbot instead
    }
}

// Initialize AI Assistant (disabled)
// const aiAssistant = new AIAssistant();

// Global function to close modal
function closeAIModal() {
    const modal = document.getElementById('ai-modal');
    if (modal) {
        modal.classList.remove('active');
    }
}

// Enhanced Chart initialization with dark theme
function initChart(canvasId, type, data, options = {}) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return null;
    
    const defaultOptions = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: {
                labels: {
                    color: '#9CA3AF',
                    font: {
                        family: 'Archivo',
                        size: 12,
                        weight: '600'
                    },
                    padding: 15,
                    usePointStyle: true
                }
            },
            tooltip: {
                backgroundColor: 'rgba(15, 23, 42, 0.8)',
                titleColor: '#F9FAFB',
                bodyColor: '#E5E7EB',
                borderColor: '#374151',
                borderWidth: 1,
                padding: 12,
                displayColors: true,
                callbacks: {
                    label: function(context) {
                        let label = context.label || '';
                        if (label) {
                            label += ': ';
                        }
                        if (context.parsed !== null) {
                            label += formatCurrency(context.parsed.y || context.parsed);
                        }
                        return label;
                    }
                }
            }
        },
        scales: type !== 'pie' && type !== 'doughnut' ? {
            y: {
                ticks: { 
                    color: '#9CA3AF',
                    font: { family: 'Archivo' }
                },
                grid: { 
                    color: 'rgba(55, 65, 81, 0.3)',
                    drawBorder: false
                },
                beginAtZero: true
            },
            x: {
                ticks: { 
                    color: '#9CA3AF',
                    font: { family: 'Archivo' }
                },
                grid: { 
                    color: 'rgba(55, 65, 81, 0.3)',
                    drawBorder: false
                }
            }
        } : {}
    };
    
    return new Chart(ctx, {
        type: type,
        data: data,
        options: { ...defaultOptions, ...options }
    });
}

// Form validation with enhanced error handling
function validateEmail(email) {
    const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return re.test(email);
}

function validatePassword(password) {
    // At least 8 chars, 1 uppercase, 1 lowercase, 1 number
    const re = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$/;
    return re.test(password);
}

function validatePhone(phone) {
    const re = /^[6-9]\d{9}$/;
    return re.test(phone);
}

function validatePIN(pin) {
    const re = /^\d{4}$/;
    return re.test(pin);
}

function validateAmount(amount) {
    return !isNaN(amount) && amount > 0;
}

function validateForm(formId) {
    const form = document.getElementById(formId);
    if (!form) return false;
    
    const inputs = form.querySelectorAll('input[required], select[required], textarea[required]');
    let isValid = true;
    
    inputs.forEach(input => {
        const value = input.value.trim();
        const type = input.type;
        let fieldValid = false;
        
        if (!value) {
            input.classList.add('is-invalid');
            fieldValid = false;
        } else {
            // Additional validation based on type
            if (type === 'email') {
                fieldValid = validateEmail(value);
            } else if (type === 'number') {
                fieldValid = validateAmount(parseFloat(value));
            } else {
                fieldValid = true;
            }
            
            if (fieldValid) {
                input.classList.remove('is-invalid');
                input.classList.add('is-valid');
            } else {
                input.classList.add('is-invalid');
            }
        }
        
        if (!fieldValid) isValid = false;
    });
    
    return isValid;
}

// Enhanced form submission handler with safe checks
function setupFormValidation(formId) {
    try {
        const form = document.getElementById(formId);
        if (!form) return;
        
        form.addEventListener('submit', function(e) {
            if (!validateForm(formId)) {
                e.preventDefault();
                if (typeof showAlert === 'function') {
                    showAlert('Please fill all required fields correctly', 'error');
                }
            }
        });
        
        // Real-time validation
        form.querySelectorAll('input, select, textarea').forEach(field => {
            if (field) {
                field.addEventListener('blur', function() {
                    if (this.hasAttribute('required')) {
                        validateForm(formId);
                    }
                });
            }
        });
    } catch (error) {
        console.error('Error setting up form validation:', error);
    }
}

// Format currency
function formatCurrency(amount) {
    return new Intl.NumberFormat('en-IN', {
        style: 'currency',
        currency: 'INR',
        minimumFractionDigits: 0,
        maximumFractionDigits: 0
    }).format(amount);
}

// Format date
function formatDate(date) {
    return new Date(date).toLocaleDateString('en-IN', {
        year: 'numeric',
        month: 'short',
        day: 'numeric'
    });
}

// Trade execution with PIN verification and enhanced error handling
async function executeTrade(tradeData) {
    try {
        // Validate trade data
        if (!tradeData.asset_type || !tradeData.symbol || !tradeData.action || !tradeData.quantity || !tradeData.price) {
            showAlert('Invalid trade data. Please check all fields.', 'error');
            return false;
        }
        
        if (tradeData.quantity <= 0 || tradeData.price <= 0) {
            showAlert('Quantity and price must be greater than zero', 'error');
            return false;
        }
        
        const pin = prompt('🔐 Enter your trading PIN to confirm:');
        if (!pin) {
            showAlert('Trade cancelled', 'info', 2000);
            return false;
        }
        
        if (!validatePIN(pin)) {
            showAlert('PIN must be 4-6 digits', 'error');
            return false;
        }
        
        // Show loading state
        const button = document.querySelector('button[onclick*="confirmTrade"]');
        const originalText = button ? button.textContent : 'Execute Trade';
        if (button) {
            button.disabled = true;
            button.textContent = '⏳ Processing...';
        }
        
        const response = await fetch('/trade/execute', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                ...tradeData,
                pin: pin
            })
        });
        
        const result = await response.json();
        
        if (response.ok && result.success) {
            showAlert('✅ ' + (result.message || 'Trade executed successfully!'), 'success', 2500);
            if (button) {
                button.disabled = false;
                button.textContent = originalText;
            }
            setTimeout(() => location.reload(), 2000);
            return true;
        } else {
            showAlert('❌ ' + (result.message || 'Trade failed'), 'error', 0);
            if (button) {
                button.disabled = false;
                button.textContent = originalText;
            }
            return false;
        }
    } catch (error) {
        console.error('Trade execution error:', error);
        showAlert('⚠️ Network error. Please check your connection.', 'error', 0);
        const button = document.querySelector('button[onclick*="confirmTrade"]');
        if (button) {
            button.disabled = false;
            button.textContent = 'Execute Trade';
        }
        return false;
    }
}

// Enhanced show alert with animations and positioning
function showAlert(message, type = 'info', duration = 3000) {
    try {
        // Ensure message is a string
        const alertMessage = String(message || 'An alert occurred');
        
        // Ensure document.body exists
        if (!document.body) {
            console.warn('Alert triggered before document body ready:', alertMessage);
            return null;
        }
        
        const alertDiv = document.createElement('div');
        alertDiv.className = `alert alert-${type}`;
        alertDiv.style.position = 'fixed';
        alertDiv.style.top = '2rem';
        alertDiv.style.right = '2rem';
        alertDiv.style.zIndex = '10000';
        alertDiv.style.minWidth = '300px';
        alertDiv.style.maxWidth = '400px';
        alertDiv.style.animation = 'slideLeft 0.3s ease-out';
        
        const closeBtn = document.createElement('button');
        closeBtn.innerHTML = '&times;';
        closeBtn.style.cssText = `
            background: none;
            border: none;
            color: inherit;
            font-size: 1.5rem;
            cursor: pointer;
            padding: 0;
            margin-left: 1rem;
        `;
        closeBtn.onclick = function() {
            try {
                alertDiv.style.animation = 'slideRight 0.3s ease-out';
                setTimeout(() => {
                    if (alertDiv && alertDiv.parentNode) {
                        alertDiv.remove();
                    }
                }, 300);
            } catch (e) {
                console.error('Error closing alert:', e);
            }
        };
        
        const content = document.createElement('div');
        content.textContent = alertMessage;
        content.style.flex = '1';
        
        alertDiv.style.display = 'flex';
        alertDiv.style.alignItems = 'center';
        alertDiv.appendChild(content);
        alertDiv.appendChild(closeBtn);
        
        document.body.appendChild(alertDiv);
        
        if (duration > 0) {
            setTimeout(() => {
                try {
                    if (alertDiv && alertDiv.parentNode) {
                        alertDiv.style.animation = 'slideRight 0.3s ease-out';
                        setTimeout(() => {
                            if (alertDiv && alertDiv.parentNode) {
                                alertDiv.remove();
                            }
                        }, 300);
                    }
                } catch (e) {
                    console.error('Error auto-closing alert:', e);
                }
            }, duration);
        }
        
        return alertDiv;
    } catch (error) {
        console.error('Critical error in showAlert:', error);
        // Fallback to browser alert
        alert(String(message || 'An alert occurred'));
        return null;
    }
}

// Add CSS animation for alerts
const style = document.createElement('style');
style.textContent = `
    @keyframes fadeOut {
        from { opacity: 1; transform: translateX(0); }
        to { opacity: 0; transform: translateX(100px); }
    }
`;
document.head.appendChild(style);

// Real-time price simulation for trading
class PriceSimulator {
    constructor() {
        this.prices = {
            'AAPL': 175.50,
            'GOOGL': 140.25,
            'MSFT': 380.75,
            'TSLA': 245.30,
            'BTC': 45000,
            'ETH': 2800,
            'GOLD': 62500,
            'SILVER': 75000
        };
        
        this.startSimulation();
    }
    
    startSimulation() {
        setInterval(() => {
            Object.keys(this.prices).forEach(symbol => {
                const change = (Math.random() - 0.5) * 0.02; // ±1% change
                this.prices[symbol] *= (1 + change);
                this.updatePriceDisplay(symbol);
            });
        }, 3000);
    }
    
    updatePriceDisplay(symbol) {
        const elements = document.querySelectorAll(`[data-symbol="${symbol}"]`);
        elements.forEach(el => {
            el.textContent = formatCurrency(this.prices[symbol]);
        });
    }
    
    getPrice(symbol) {
        return this.prices[symbol] || 0;
    }
}

// Initialize price simulator if on trade page
if (window.location.pathname.includes('trade')) {
    const priceSimulator = new PriceSimulator();
    window.priceSimulator = priceSimulator;
}

// Smooth scroll
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
        e.preventDefault();
        const target = document.querySelector(this.getAttribute('href'));
        if (target) {
            target.scrollIntoView({
                behavior: 'smooth',
                block: 'start'
            });
        }
    });
});

// Initialize tooltips with safe checks
function initTooltips() {
    try {
        const tooltips = document.querySelectorAll('[data-tooltip]');
        tooltips.forEach(el => {
            if (el) {
                el.style.position = 'relative';
                el.style.cursor = 'help';
                
                el.addEventListener('mouseenter', function() {
                    const tooltip = document.createElement('div');
                    tooltip.className = 'tooltip-popup';
                    tooltip.textContent = this.getAttribute('data-tooltip');
                    tooltip.style.cssText = `
                        position: absolute;
                        bottom: 100%;
                        left: 50%;
                        transform: translateX(-50%);
                        background: var(--bg-elevated);
                        color: var(--text-primary);
                        padding: 0.5rem 1rem;
                        border-radius: 6px;
                        font-size: 0.875rem;
                        white-space: nowrap;
                        margin-bottom: 0.5rem;
                        z-index: 1000;
                        box-shadow: var(--shadow-md);
                    `;
                    this.appendChild(tooltip);
                });
                
                el.addEventListener('mouseleave', function() {
                    const tooltip = this.querySelector('.tooltip-popup');
                    if (tooltip) tooltip.remove();
                });
            }
        });
    } catch (error) {
        console.error('Error initializing tooltips:', error);
    }
}

// Initialize on page load with better structure
// Global error handler to prevent crashes
window.onerror = function(msg, url, lineNo, columnNo, error) {
    console.error('Global error caught:', {
        message: msg,
        source: url,
        line: lineNo,
        column: columnNo,
        error: error
    });
    
    // Only show alert for critical errors
    if (msg.includes('undefined') || msg.includes('not a function')) {
        if (typeof showAlert === 'function') {
            showAlert('⚠️ Application encountered an error. Please refresh the page.', 'error', 5000);
        }
    }
    
    return true; // Prevent default error handling
};

// Handle unhandled promise rejections
window.onunhandledrejection = function(event) {
    console.error('Unhandled promise rejection:', event.reason);
    event.preventDefault();
};

// DOMContentLoaded event to initialize app
document.addEventListener('DOMContentLoaded', function() {
    console.log('Initializing Finance App...');
    
    try {
        // Initialize tooltips
        initTooltips();
        
        // Add fade-in animation to cards
        const cards = document.querySelectorAll('.card, .stat-card');
        cards.forEach((card, index) => {
            if (card) {
                card.style.animation = `fadeInUp 0.5s ease-out ${index * 0.1}s backwards`;
            }
        });
        
        // Setup form validation for all forms
        document.querySelectorAll('form').forEach(form => {
            const formId = form.id;
            if (formId) {
                setupFormValidation(formId);
            }
        });
        
        // Handle flash messages auto-hide
        const alerts = document.querySelectorAll('.alert');
        alerts.forEach(alert => {
            if (alert && (!alert.style.position || alert.style.position !== 'fixed')) {
                setTimeout(() => {
                    if (alert && alert.parentNode) {
                        alert.style.animation = 'fadeOut 0.3s ease-out';
                        setTimeout(() => {
                            if (alert && alert.parentNode) {
                                alert.style.display = 'none';
                            }
                        }, 300);
                    }
                }, 5000);
            }
        });
        
        // Initialize focused input styling
        document.querySelectorAll('input, select, textarea').forEach(field => {
            if (field) {
                field.addEventListener('focus', function() {
                    if (this.parentElement) {
                        this.parentElement.classList.add('focused');
                    }
                });
                field.addEventListener('blur', function() {
                    if (this.parentElement) {
                        this.parentElement.classList.remove('focused');
                    }
                });
            }
        });
        
        // Add keyboard navigation hints
        document.addEventListener('keydown', function(e) {
            if (e.ctrlKey || e.metaKey) {
                // Ctrl+1 = Dashboard, Ctrl+2 = Wallet, etc
                const key = e.key;
                if (key === '1') window.location.href = '/dashboard';
                if (key === '2') window.location.href = '/wallet';
                if (key === '3') window.location.href = '/expenses';
                if (key === '4') window.location.href = '/trade';
            }
        });
        
        console.log('Finance App initialized successfully');
    } catch (error) {
        console.error('Error during app initialization:', error);
    }
});

// Chatbot functionality
class FinancialChatbot {
    constructor() {
        this.isOpen = false;
        this.init();
    }
    
    init() {
        const toggle = document.getElementById('chat-toggle');
        const sendBtn = document.getElementById('send-chat');
        const input = document.getElementById('chat-input');
        
        if (toggle) toggle.onclick = () => this.toggleChat();
        if (sendBtn) sendBtn.onclick = () => this.sendMessage();
        if (input) {
            input.onkeypress = (e) => {
                if (e.key === 'Enter') this.sendMessage();
            };
        }
        
        this.addMessage('Hello! I\'m your FinTech AI assistant powered by Ollama. Ask me about your expenses, investments, or financial goals!', 'bot');
    }
    
    toggleChat() {
        const window = document.getElementById('chat-window');
        this.isOpen = !this.isOpen;
        window.style.display = this.isOpen ? 'block' : 'none';
    }
    
    async sendMessage() {
        const input = document.getElementById('chat-input');
        const message = input.value.trim();
        
        if (!message) return;
        
        this.addMessage(message, 'user');
        input.value = '';
        
        this.addMessage('Thinking...', 'bot', true);
        
        try {
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: message })
            });
            
            const data = await response.json();
            
            // Remove thinking message
            const messages = document.getElementById('chat-messages');
            messages.removeChild(messages.lastChild);
            
            if (data.response) {
                this.addMessage(data.response, 'bot');
            } else {
                this.addMessage(data.error || 'Sorry, I could not process your request.', 'bot');
            }
        } catch (error) {
            const messages = document.getElementById('chat-messages');
            messages.removeChild(messages.lastChild);
            this.addMessage('Error connecting to AI service. Please try again.', 'bot');
        }
    }
    
    addMessage(text, sender, isTemporary = false) {
        const messages = document.getElementById('chat-messages');
        const div = document.createElement('div');
        div.style.cssText = `
            margin-bottom: 1rem;
            padding: 0.75rem;
            border-radius: 8px;
            ${sender === 'user' ? 
                'background: var(--primary); color: white; margin-left: 2rem; text-align: right;' : 
                'background: var(--bg-elevated); color: var(--text-primary); margin-right: 2rem;'
            }
        `;
        div.textContent = text;
        messages.appendChild(div);
        messages.scrollTop = messages.scrollHeight;
    }
}

// Initialize chatbot
const chatbot = new FinancialChatbot();

// Export functions for use in templates
window.formatCurrency = formatCurrency;
window.formatDate = formatDate;
window.executeTrade = executeTrade;
window.showAlert = showAlert;
window.validateForm = validateForm;
window.validatePIN = validatePIN;
window.initChart = initChart;