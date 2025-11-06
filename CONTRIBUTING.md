# Contributing to Crypto Price Alert Bot

Thanks for your interest in contributing! This project is a lightweight Telegram bot that checks spot prices across multiple exchanges (Binance, Binance Alpha, Bybit, MEXC, KuCoin, OKX, Gate, Bitget) and triggers burst alerts.  
To keep the repo clean and easy to maintain, please follow the guidelines below.

---

## Table of Contents
- [Project Setup](#project-setup)
- [Branching Model](#branching-model)
- [Commit Style (Conventional Commits)](#commit-style-conventional-commits)
- [Pull Request Guidelines](#pull-request-guidelines)
- [Coding Guidelines](#coding-guidelines)
- [Adding a New Exchange Provider](#adding-a-new-exchange-provider)
- [Environment & Secrets](#environment--secrets)
- [Testing & Linters](#testing--linters)
- [Changelog & Releases](#changelog--releases)
- [Security: Reporting Vulnerabilities](#security-reporting-vulnerabilities)
- [License](#license)

---

## Project Setup

### Requirements
- Python **3.10+** (tested with 3.12)
- `python-telegram-bot[job-queue]==20.7`
- `requests`
- `python-dotenv`

Install deps:

```bash
pip install -r requirements.txt
