#!/bin/bash
git describe --always > VERSION
date >> VERSION
echo "Updated VERSION file"