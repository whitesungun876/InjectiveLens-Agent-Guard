// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract AssessmentLogger {
    struct AssessmentRecord {
        address signer;
        bytes32 walletHash;
        bytes32 evidenceBundleHash;
        bytes32 recommendationHash;
        uint256 walletRiskScoreBps;
        string riskLevel;
        string decisionType;
        string actionType;
        string assessmentURI;
        uint256 recordedAt;
    }

    mapping(bytes32 => AssessmentRecord) public records;

    event AssessmentRecorded(
        bytes32 indexed assessmentHash,
        bytes32 indexed walletHash,
        address indexed signer,
        bytes32 evidenceBundleHash,
        bytes32 recommendationHash,
        uint256 walletRiskScoreBps,
        string riskLevel,
        string decisionType,
        string actionType,
        string assessmentURI
    );

    function recordAssessment(
        bytes32 assessmentHash,
        bytes32 walletHash,
        bytes32 evidenceBundleHash,
        bytes32 recommendationHash,
        uint256 walletRiskScoreBps,
        string calldata riskLevel,
        string calldata decisionType,
        string calldata actionType,
        string calldata assessmentURI
    ) external returns (bytes32 recordId) {
        recordId = keccak256(abi.encodePacked(assessmentHash, msg.sender));
        records[recordId] = AssessmentRecord({
            signer: msg.sender,
            walletHash: walletHash,
            evidenceBundleHash: evidenceBundleHash,
            recommendationHash: recommendationHash,
            walletRiskScoreBps: walletRiskScoreBps,
            riskLevel: riskLevel,
            decisionType: decisionType,
            actionType: actionType,
            assessmentURI: assessmentURI,
            recordedAt: block.timestamp
        });

        emit AssessmentRecorded(
            assessmentHash,
            walletHash,
            msg.sender,
            evidenceBundleHash,
            recommendationHash,
            walletRiskScoreBps,
            riskLevel,
            decisionType,
            actionType,
            assessmentURI
        );
    }
}
