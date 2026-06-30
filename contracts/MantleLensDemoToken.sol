// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

interface IMantleLensDemoToken {
    function transfer(address to, uint256 amount) external returns (bool);
}

contract MantleLensDemoToken {
    string public constant name = "MantleLens Demo Token";
    string public constant symbol = "MLDT";
    uint8 public constant decimals = 18;
    uint256 public totalSupply;

    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    event Transfer(address indexed from, address indexed to, uint256 amount);
    event Approval(address indexed owner, address indexed spender, uint256 amount);

    constructor(uint256 initialSupply) {
        _mint(msg.sender, initialSupply);
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        _transfer(msg.sender, to, amount);
        return true;
    }

    function approve(address spender, uint256 amount) external returns (bool) {
        require(spender != address(0), "spender is zero");
        allowance[msg.sender][spender] = amount;
        emit Approval(msg.sender, spender, amount);
        return true;
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        uint256 currentAllowance = allowance[from][msg.sender];
        require(currentAllowance >= amount, "allowance too low");
        if (currentAllowance != type(uint256).max) {
            allowance[from][msg.sender] = currentAllowance - amount;
            emit Approval(from, msg.sender, allowance[from][msg.sender]);
        }
        _transfer(from, to, amount);
        return true;
    }

    function _transfer(address from, address to, uint256 amount) internal {
        require(to != address(0), "recipient is zero");
        require(balanceOf[from] >= amount, "balance too low");
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
        emit Transfer(from, to, amount);
    }

    function _mint(address to, uint256 amount) internal {
        require(to != address(0), "recipient is zero");
        totalSupply += amount;
        balanceOf[to] += amount;
        emit Transfer(address(0), to, amount);
    }
}

contract MantleLensDemoSpender {
    event DemoDustSent(address indexed token, address indexed to, uint256 amount);

    function sendDust(address token, address to, uint256 amount) external returns (bool) {
        require(token != address(0), "token is zero");
        require(to != address(0), "recipient is zero");
        bool ok = IMantleLensDemoToken(token).transfer(to, amount);
        require(ok, "dust transfer failed");
        emit DemoDustSent(token, to, amount);
        return true;
    }
}
